"""Orchestrator: every side effect in Last Wishes goes through here (LAST_WISHES.md §8).

All cross-module calls live in this file so wiring changes happen in one place.
Other modules are imported lazily and defensively: if one is missing, the call
raises ModuleNotReady and the UI shows a plain "module not ready" message.
Nothing here invents numbers — amounts only come from extraction output.

Persistence: canonical rows go to db.py (SingleStore). Small pieces of UI-visible
metadata that have no dedicated table (chosen plan, persona inquiry, selection,
approval card ids, reply diffs, last recall) are stored in the audit log, so the
whole app state can be rebuilt from DB + Cognee after a restart.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
FTC_PATH = DATA_DIR / "ftc_reference.txt"
WISH_FILES = ("wishes_linda.txt", "confirmation_daughter.txt")
ACTOR = "agent"
REVIEWER = "daughter"


class ModuleNotReady(RuntimeError):
    """A module another agent owns is missing or lacks the expected function."""

    def __init__(self, module: str, detail: str = ""):
        self.module = module
        super().__init__(f"Module not ready: {module}" + (f" ({detail})" if detail else ""))


class ApprovalBlocked(RuntimeError):
    """An approval cannot be sent (invalidated, identity not verified, ...)."""


# ---------------------------------------------------------------------------
# Defensive module access
# ---------------------------------------------------------------------------

MODULES = {
    "extract": "pipeline.extract",
    "classify": "pipeline.classify",
    "flags": "pipeline.flags",
    "optimizer": "pipeline.optimizer",
    "wishes": "pipeline.wishes",
    "memory": "memory.cognee_mem",
    "db": "db",
    "approvals": "approvals",
    "outbox": "outbox",
    "persona": "persona",
}


def _mod(key: str):
    name = MODULES[key]
    try:
        return importlib.import_module(name)
    except ImportError as e:  # missing file or its dependency
        raise ModuleNotReady(name, str(e)) from e


def _fn(key: str, *names: str) -> Callable:
    m = _mod(key)
    for n in names:
        f = getattr(m, n, None)
        if callable(f):
            return f
    raise ModuleNotReady(MODULES[key], f"no function {' / '.join(names)}")


def _call(fn: Callable, *args, **kwargs):
    """Call fn, passing a DB connection if it wants one and dropping kwargs it doesn't accept."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    params = sig.parameters
    has_var_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
    first = next(iter(params.values()), None)
    if first is not None and first.name == "conn" and "conn" not in kwargs and fn.__module__ != __name__:
        args = (_db_conn(),) + args
    if not has_var_kw:
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    return fn(*args, **kwargs)


def _db_conn():
    return _fn("db", "get_conn")()


def db(name: str, *args, **kwargs):
    return _call(_fn("db", name), *args, **kwargs)


def init() -> None:
    """Create tables if needed. Safe on every app run."""
    _fn("db", "init_schema")()


def module_status() -> dict[str, str]:
    """'ok' or the reason a module is not ready — shown in the sidebar."""
    out = {}
    for key, name in MODULES.items():
        try:
            _mod(key)
            out[name] = "ok"
        except ModuleNotReady as e:
            out[name] = f"not ready: {e}"
    return out


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def audit(action: str, detail: dict | None = None, actor: str = ACTOR) -> None:
    db("audit", actor=actor, action=action, detail=detail or {}, detail_json=detail or {})


def remember(name: str, *args, **kwargs):
    """Write to Cognee memory. DB stays the source of truth: if memory isn't ready, the step
    continues and the skipped write is recorded in the audit log (shown in the UI)."""
    try:
        return _call(_fn("memory", name), *args, **kwargs)
    except ModuleNotReady as e:
        audit("memory_write_skipped", {"call": name, "reason": str(e)})
        return None


def memory_skips() -> int:
    return len(audit_events("memory_write_skipped"))


def _jsonish(v):
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, (bytes, bytearray)):
        v = v.decode()
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def audit_events(action: str | None = None) -> list[dict]:
    """Audit rows (oldest first) with detail decoded to a dict."""
    rows = db("list_audit", limit=100000) or []
    out = []
    for r in rows:
        r = dict(r)
        d = r.get("detail_json", r.get("detail"))
        r["detail"] = _jsonish(d) if d is not None else {}
        if action is None or r.get("action") == action:
            out.append(r)
    out.sort(key=lambda r: str(r.get("ts") or ""))
    return out


def last_event(action: str, **match) -> Optional[dict]:
    for r in reversed(audit_events(action)):
        d = r["detail"] if isinstance(r["detail"], dict) else {}
        if all(d.get(k) == v for k, v in match.items()):
            return d
    return None


def provider_from_filename(path: str) -> Optional[str]:
    """'quote_A.txt' -> 'A', 'reply_B_v2.txt' -> 'B'. Generic: no per-provider logic."""
    stem = Path(path).stem
    m = re.match(r"(?:quote|reply|gpl|price[_-]?list)[_-]([A-Za-z0-9]+)", stem, re.I)
    return m.group(1).upper() if m else None


def read_document(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError as e:
            raise ModuleNotReady("pypdf", "needed to read PDF price lists") from e
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    return p.read_text(encoding="utf-8")


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def find_recipient(text: str) -> Optional[str]:
    m = _EMAIL.search(text or "")
    return m.group(0) if m else None


def quote_id_for(provider: str, version: int) -> str:
    return f"{provider}-v{version}"


def fmt_money(low: Optional[float], high: Optional[float] = None, price_type: str | None = None) -> str:
    """Unknown is never $0: it is 'Unresolved'."""
    if price_type == "unknown" or (low is None and high is None):
        return "Unresolved"
    if high is None and price_type == "starting_at":
        return f"from ${low:,.0f}"
    if low is None:
        return f"up to ${high:,.0f}"
    if high is None or abs(high - low) < 0.005:
        return f"${low:,.2f}".replace(".00", "")
    return f"${low:,.0f}–${high:,.0f}"


def item_amount_text(item: dict) -> str:
    return fmt_money(item.get("amount_low"), item.get("amount_high"), item.get("price_type"))


# ---------------------------------------------------------------------------
# Validation + normalization (pipeline steps 4–5, code only)
# ---------------------------------------------------------------------------


def validate_items(items: list[dict], quote_id: str, provider: str, source_doc: str) -> tuple[list[dict], list[str]]:
    """Make every item contract-shaped; never turn unknown into 0. Returns (items, issues)."""
    issues: list[str] = []
    out: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(items, 1):
        it = dict(raw)
        it.setdefault("item_id", f"{provider}-{i:02d}")
        if it["item_id"] in seen:
            it["item_id"] = f"{it['item_id']}-{i}"
        seen.add(it["item_id"])
        it["quote_id"] = quote_id
        it["provider"] = provider
        it.setdefault("source_doc", source_doc)
        it.setdefault("confidence", 0.0)
        it.setdefault("category", "optional")
        lo, hi = it.get("amount_low"), it.get("amount_high")
        if it.get("price_type") not in ("fixed", "estimated", "starting_at", "unknown"):
            it["price_type"] = "unknown" if lo is None and hi is None else "estimated"
        if it["price_type"] == "unknown":
            it["amount_low"] = it["amount_high"] = None
        elif lo is None and hi is None:
            it["price_type"] = "unknown"
            issues.append(f"{it['item_id']}: priced type without an amount — marked unresolved")
        if not (it.get("excerpt") or "").strip():
            issues.append(f"{it['item_id']}: no source excerpt — needs reviewer check")
            it["confidence"] = min(float(it.get("confidence") or 0), 0.3)
        out.append(it)
    return out, issues


# ---------------------------------------------------------------------------
# Quote v2 merge (pipeline step 13) — pure, tested
# ---------------------------------------------------------------------------

_STOP = {
    "a", "an", "the", "of", "and", "or", "for", "to", "up", "in", "on", "at", "with", "per",
    "fee", "fees", "charge", "charges", "cost", "costs", "price", "prices", "amount",
    "day", "days", "within", "mile", "miles", "usd", "revised", "updated", "new",
}
_TOTAL = re.compile(r"\btotal\b", re.I)


def normalize_name(name: str) -> frozenset[str]:
    toks = re.findall(r"[a-z]+", (name or "").lower())
    out = set()
    for t in toks:
        if t in _STOP or len(t) < 2:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.add(t)
    return frozenset(out)


def _match_score(a: frozenset, b: frozenset) -> tuple[float, float]:
    if not a or not b:
        return (0.0, 0.0)
    inter = len(a & b)
    return (inter / len(a | b), inter / min(len(a), len(b)))


def merge_reply(v1_items: list[dict], reply_items: list[dict], new_quote_id: str, provider: str) -> tuple[list[dict], list[dict]]:
    """Quote v2 = v1 items, updated by reply items matched on normalized name.

    Returns (v2_items, changes). Unmatched v1 items are carried unchanged;
    unmatched reply items are added. Total lines in the reply are skipped
    (they are derived, not line items). Prefers matching a v1 item whose price
    was unresolved when two candidates score the same.
    """
    version = new_quote_id.rsplit("-v", 1)[-1]
    v2 = [dict(it) for it in v1_items]
    for it in v2:
        it["v1_item_id"] = it["item_id"]
    used: set[int] = set()
    changes: list[dict] = []
    added = 0
    for r in reply_items:
        if _TOTAL.search(r.get("name") or ""):
            continue
        rn = normalize_name(r.get("name", ""))
        best, best_key = None, None
        for idx, it in enumerate(v2):
            if idx in used:
                continue
            jac, cont = _match_score(rn, normalize_name(it.get("name", "")))
            if jac >= 0.5 or cont >= 0.999:
                key = (jac, cont, it.get("price_type") == "unknown")
                if best_key is None or key > best_key:
                    best, best_key = idx, key
        # SIE can name a reply line after its last phrase (for example "county's
        # cost") even when the excerpt names the original service. Match on that
        # verbatim excerpt before treating it as a newly added charge.
        if best is None:
            excerpt_tokens = normalize_name(r.get("excerpt", ""))
            for idx, it in enumerate(v2):
                if idx in used:
                    continue
                old_tokens = normalize_name(it.get("name", ""))
                _, coverage = _match_score(old_tokens, excerpt_tokens)
                if len(old_tokens & excerpt_tokens) >= 2 and coverage >= 0.75:
                    key = (coverage, it.get("price_type") == "unknown")
                    if best_key is None or key > best_key:
                        best, best_key = idx, key
        if best is None:
            added += 1
            new = dict(r)
            new["item_id"] = f"{provider}-R{added:02d}"
            new["v1_item_id"] = None
            new["provider"] = provider
            new["quote_id"] = new_quote_id
            v2.append(new)
            used.add(len(v2) - 1)
            changes.append({"kind": "added", "name": new.get("name"), "new": new})
            continue
        used.add(best)
        old = dict(v2[best])
        upd = v2[best]
        for k in ("price_type", "amount_low", "amount_high", "excerpt", "source_doc", "confidence"):
            if k in r:
                upd[k] = r[k]
        same_price = (old.get("amount_low"), old.get("amount_high"), old.get("price_type")) == (
            upd.get("amount_low"), upd.get("amount_high"), upd.get("price_type"))
        kind = "resolved" if old.get("price_type") == "unknown" and upd.get("price_type") != "unknown" else (
            "confirmed" if same_price else "changed")
        changes.append({"kind": kind, "name": upd.get("name"), "old": old, "new": dict(upd)})
    for it in v2:
        it["quote_id"] = new_quote_id
        if it.get("v1_item_id"):
            it["item_id"] = f"{it['v1_item_id']}.v{version}"
    return v2, changes


def line_diff(v1_items: list[dict], v2_items: list[dict]) -> list[dict]:
    """Line-by-line v1 vs v2 for the Diff tab (by v1_item_id, then normalized name)."""
    by_id = {it.get("item_id"): it for it in v1_items}
    by_name = {normalize_name(it.get("name", "")): it for it in v1_items}
    rows, seen = [], set()
    for it in v2_items:
        base = it.get("v1_item_id") or str(it.get("item_id", "")).rsplit(".v", 1)[0]
        old = by_id.get(base) or by_name.get(normalize_name(it.get("name", "")))
        if old is not None:
            seen.add(old.get("item_id"))
        old_txt = item_amount_text(old) if old else "—"
        new_txt = item_amount_text(it)
        if old is None:
            status = "added"
        elif old.get("price_type") == "unknown" and it.get("price_type") != "unknown":
            status = "resolved"
        elif old_txt != new_txt:
            status = "changed"
        else:
            status = "unchanged"
        rows.append({"name": it.get("name"), "v1": old_txt, "v2": new_txt, "status": status,
                     "old_low": old.get("amount_low") if old else None, "old_high": old.get("amount_high") if old else None,
                     "new_low": it.get("amount_low"), "new_high": it.get("amount_high"),
                     "v2_excerpt": it.get("excerpt", "")})
    for it in v1_items:
        if it.get("item_id") not in seen and not any(r["name"] == it.get("name") for r in rows):
            rows.append({"name": it.get("name"), "v1": item_amount_text(it), "v2": "—", "status": "removed",
                         "old_low": it.get("amount_low"), "old_high": it.get("amount_high"),
                         "new_low": None, "new_high": None, "v2_excerpt": ""})
    return rows


# ---------------------------------------------------------------------------
# State readers (DB + audit) — used by the UI on every run
# ---------------------------------------------------------------------------


def norm_item(row: dict) -> dict:
    it = dict(row)
    it.setdefault("item_id", it.get("id"))
    if "estimated_low" in it and "amount_low" not in it:
        it["amount_low"] = it["estimated_low"]
    for k in ("amount_low", "amount_high"):
        if it.get(k) is not None:
            it[k] = float(it[k])
    if it.get("price_type") == "unknown":
        it["amount_low"] = it["amount_high"] = None
    return it


def quotes() -> list[dict]:
    rows = [dict(r) for r in (db("list_quotes") or [])]
    for r in rows:
        r.setdefault("quote_id", r.get("id"))
        r["version"] = int(r.get("version") or 1)
    return sorted(rows, key=lambda r: (str(r.get("provider")), r["version"]))


def latest_quotes() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for q in quotes():
        if q["provider"] not in out or q["version"] > out[q["provider"]]["version"]:
            out[q["provider"]] = q
    return out


def quote_items(quote_id: str) -> list[dict]:
    items = [norm_item(r) for r in (db("get_quote_items", quote_id) or [])]
    for it in items:
        it.setdefault("quote_id", quote_id)
        it.setdefault("provider", quote_id.rsplit("-v", 1)[0])
    return items


def wishes() -> list[dict]:
    """Wish rows from the DB, with kind/value re-derived by pipeline.wishes rules (not stored)."""
    parse = _fn("wishes", "parse_wishes")
    rows = [dict(r) for r in (db("list_wishes") or [])]
    for r in rows:
        r.setdefault("wish_id", r.get("id"))
        if "kind" not in r:
            parsed = {w["wish_id"]: w for w in parse(r.get("text") or "", r.get("source_id"))}
            w = parsed.get(r["wish_id"]) or {}
            r["kind"] = w.get("kind", "other")
            r["value"] = w.get("value")
    return sorted(rows, key=lambda r: str(r["wish_id"]))


def flags(quote_id: str | None = None) -> list[dict]:
    rows = [dict(r) for r in (db("list_flags") or [])]
    for r in rows:
        r.setdefault("flag_id", r.get("id"))
    return [r for r in rows if quote_id is None or r.get("quote_id") == quote_id]


def plans() -> list[dict]:
    """Plans from the DB (full contract shape + 'stale'), oldest first."""
    out = []
    for r in db("list_plans") or []:
        p = dict(r)
        p.setdefault("plan_id", p.get("id"))
        p["stale"] = bool(p.get("stale"))
        out.append(p)
    return out


def chosen_plan() -> Optional[dict]:
    d = last_event("analysis_run")
    if not d:
        return None
    for p in plans():
        if p["plan_id"] == d.get("chosen_plan_id") and not p["stale"]:
            return p
    return None


def plan_for_quote(quote_id: str) -> Optional[dict]:
    cands = [p for p in plans() if p.get("quote_id") == quote_id and not p["stale"]]
    return cands[-1] if cands else None


def sie_calls() -> list[dict]:
    return [dict(r) for r in (db("list_sie_calls") or [])]


# ---------------------------------------------------------------------------
# Step 1: wishes
# ---------------------------------------------------------------------------


def _source_id(text: str, fallback: str) -> str:
    m = re.search(r"^SOURCE:\s*(\S+)", text, re.M)
    return m.group(1) if m else fallback


def _speaker(text: str) -> Optional[str]:
    """First name from a 'SPEAKER:' or 'FROM:' header line, if the document has one."""
    m = re.search(r"^(?:SPEAKER|FROM):\s*([A-Z][\w'-]+)", text, re.M)
    return m.group(1) if m else None


def ingest_wishes(paths: list[str | Path] | None = None) -> list[dict]:
    parse = _fn("wishes", "parse_wishes")
    merge = _fn("wishes", "merge_wishes")
    groups = []
    existing = {w["wish_id"] for w in wishes()}
    speakers = []
    for p in paths or [DATA_DIR / f for f in WISH_FILES]:
        p = Path(p)
        raw = p.read_text(encoding="utf-8")
        sid = _source_id(raw, p.stem)
        speakers.append((_speaker(raw), sid))
        db("insert_document", kind="wish_note", provider=None, filename=p.name, raw_text=raw,
           is_fictional=True, source_url=None)
        groups.append(parse(raw, sid))
    merged = merge(*groups)
    # A wish is confirmed when more than one source states it (e.g. the note + the family confirmation).
    confirmed = {w["wish_id"] for g in groups[1:] for w in g}
    for w in merged:
        if w["wish_id"] in existing:
            continue
        db("insert_wish", w["text"], w["source_id"], wish_id=w["wish_id"],
           confirmed_by=REVIEWER if w["wish_id"] in confirmed else None)
        stated_by = next((sp for sp, sid in speakers if sid == w["source_id"] and sp), None)
        kw = {"stated_by": stated_by} if stated_by else {}
        remember("remember_wish", w["text"], w["source_id"], wish_id=w["wish_id"], **kw)
        audit("wish_ingested", {"wish_id": w["wish_id"], "kind": w.get("kind"), "value": w.get("value"),
                                "source_id": w["source_id"]})
    for (member, sid), g in list(zip(speakers, groups))[1:]:
        ids = [w["wish_id"] for w in g]
        if member and ids:
            remember("remember_confirmation", member, ids, source_id=sid)
    audit("wishes_loaded", {"count": len(merged), "files": [str(Path(p).name) for p in (paths or WISH_FILES)]})
    return merged


# ---------------------------------------------------------------------------
# Steps 2–5: read a quote
# ---------------------------------------------------------------------------


def _extract_and_classify(text: str, source_doc: str, quote_id: str) -> tuple[list[dict], list[dict]]:
    extract = _fn("extract", "extract_quote")
    classify = _fn("classify", "classify", "classify_items")
    items, traces = extract(text, source_doc, quote_id)
    items, ctraces = classify(items)
    return list(items), list(traces or []) + list(ctraces or [])


def _log_traces(traces: list[dict], items: list[dict], quote_id: str) -> None:
    for t in traces:
        t = dict(t)
        output = t.pop("output", None) or t.pop("output_json", None)
        if output is None:
            output = {"quote_id": quote_id,
                      "excerpts": [it.get("excerpt", "")[:160] for it in items[:5]]}
        db("log_sie_call", t, output)


def ingest_document(path: str | Path, provider: str | None = None, version: int = 1,
                    is_fictional: bool = True, source_url: str | None = None) -> dict:
    """extract → classify → validate → quotes/line_items → sie_calls → Cognee."""
    path = Path(path)
    provider = (provider or provider_from_filename(path.name) or "").strip().upper()
    if not provider:
        raise ValueError(f"Choose a provider letter for {path.name}")
    text = read_document(path)
    quote_id = quote_id_for(provider, version)
    doc_id = db("insert_document", kind="quote", provider=provider, filename=path.name, raw_text=text,
                is_fictional=is_fictional, source_url=source_url)
    items, traces = _extract_and_classify(text, path.name, quote_id)
    items, issues = validate_items(items, quote_id, provider, path.name)
    db("insert_quote", provider, version, quote_id=quote_id, supersedes_id=None, document_id=doc_id)
    db("insert_line_items", items)
    _log_traces(traces, items, quote_id)
    remember("remember_quote", quote_id, provider, version, items, supersedes=None)
    db("mark_plans_stale", provider)
    audit("document_ingested", {"provider": provider, "quote_id": quote_id, "filename": path.name,
                                "items": len(items), "validation_issues": issues,
                                "recipient": find_recipient(text), "is_fictional": is_fictional})
    return {"quote_id": quote_id, "items": items, "issues": issues, "traces": len(traces)}


# ---------------------------------------------------------------------------
# Steps 6 + 8: flags and plan
# ---------------------------------------------------------------------------


def _ftc_refs():
    return _fn("flags", "load_ftc_refs")(str(FTC_PATH))


def run_analysis() -> dict:
    latest = latest_quotes()
    if not latest:
        raise ValueError("No quotes yet — read quotes first.")
    ws = wishes()
    if not ws:
        raise ValueError("No wishes yet — load the wishes first.")
    quotes_dict = {q["quote_id"]: quote_items(q["quote_id"]) for q in latest.values()}
    all_items = [it for items in quotes_dict.values() for it in items]
    fl = _call(_fn("flags", "review_flags"), all_items, ws, _ftc_refs()) or []
    for qid in quotes_dict:  # re-running rules replaces that quote's flags
        db("delete_flags", qid)
    if fl:
        db("insert_flags", fl)
    for prov in latest:
        db("mark_plans_stale", prov)
    best, alts = _fn("optimizer", "best_plan")(quotes_dict, ws)
    stored = {}
    for p in [*(alts or []), best]:
        if p and p["plan_id"] not in stored:
            db("upsert_plan", p, stale=False)
            stored[p["plan_id"]] = p
    if best:
        remember("remember_plan", best)
    audit("analysis_run", {"chosen_plan_id": best["plan_id"] if best else None,
                           "quotes": list(quotes_dict), "flags": len(fl or [])})
    return {"plan": best, "alternatives": alts, "flags": fl}


# ---------------------------------------------------------------------------
# Steps 9–10: clarification + approval #1
# ---------------------------------------------------------------------------


def recipient_for(provider: str) -> str:
    for kind in ("reply_ingested", "document_ingested"):
        d = last_event(kind, provider=provider)
        if d and d.get("recipient"):
            return d["recipient"]
    return f"Provider {provider} (fictional) — sandbox outbox"


def prepare_clarification(provider: str) -> dict:
    import drafting

    q = latest_quotes().get(provider)
    if not q:
        raise ValueError(f"No quote for provider {provider}")
    qid = q["quote_id"]
    fl = [f for f in flags(qid) if f.get("kind") in ("unresolved_charge", "stated_requirement")]
    if not fl:
        raise ValueError(f"No open review flags for {qid}")
    plan = plan_for_quote(qid)
    items = {it["item_id"]: it for it in quote_items(qid)}
    body = drafting.draft_clarification(fl, plan, provider, items=items)
    recipient = recipient_for(provider)
    questions = []
    for f in fl:
        qq = f"Q-{qid}-{f.get('flag_id')}"
        name = (items.get(f.get("item_id")) or {}).get("name") or drafting.flag_subject(f)
        remember("remember_question", qq, qid, name, text=f.get("message") or f.get("excerpt"))
        questions.append(qq)
    card = _prepare_card("clarification", qid, recipient, body,
                         {"provider": provider, "question_ids": questions,
                          "flags": [f.get("flag_id") for f in fl]})
    audit("clarification_drafted", {"approval_id": card["approval_id"], "provider": provider, "quote_id": qid,
                                    "question_ids": questions})
    return card


def _card_view(row: dict) -> dict:
    c = dict(row)
    c["approval_id"] = c.get("id")
    extra = c.get("extra")
    if extra is None:
        extra = _jsonish(c.get("extra_json")) or {}
    c["extra"] = extra if isinstance(extra, dict) else {}
    c.setdefault("provider", c["extra"].get("provider") or str(c.get("quote_id", "")).rsplit("-v", 1)[0])
    return c


def _prepare_card(kind: str, quote_id: str, recipient: str, body: str, extra: dict | None = None) -> dict:
    try:
        row = _call(_fn("approvals", "prepare_card"), kind, quote_id, recipient, body, extra or {}, actor=ACTOR)
    except Exception as ex:
        if type(ex).__name__ == "ApprovalInvalidated":
            raise ApprovalBlocked(str(ex)) from ex
        raise
    return _card_view(row)


def approval_cards(kind: str | None = None) -> list[dict]:
    """Approval cards from the approvals table, with live validity + outbox row."""
    ap = _mod("approvals")
    ob = _mod("outbox")
    cards = []
    for row in db("list_approvals") or []:
        c = _card_view(row)
        if kind and c.get("kind") != kind:
            continue
        sent_row = ob.get_by_approval(c["approval_id"])
        c["outbox"] = sent_row
        c["sent"] = sent_row if sent_row and sent_row.get("status") == "sent" else None
        c["valid"] = bool(c["sent"]) or bool(ap.is_valid(row))
        cards.append(c)
    return cards


def get_card(approval_id) -> Optional[dict]:
    return next((c for c in approval_cards() if c["approval_id"] == approval_id), None)


def approve_and_send(approval_id, persona_inquiry_id: str | None = None) -> dict:
    """Approve exactly this one message, then send once (outbox is idempotent)."""
    card = get_card(approval_id)
    if card is None:
        raise ValueError(f"Unknown approval {approval_id}")
    if card.get("sent"):
        return card["sent"]
    if not card["valid"]:
        raise ApprovalBlocked("This approval was invalidated because the quote changed. Rebuild the card.")
    if card["kind"] == "arrangement":
        if not persona_inquiry_id or not _fn("persona", "is_approved")(persona_inquiry_id):
            raise ApprovalBlocked("Identity check is not approved yet.")
    try:
        if card.get("status") == "pending":
            _fn("approvals", "approve")(approval_id, REVIEWER, persona_inquiry_id)
        # status 'approved' = an earlier send failed; outbox.send retries the same row
        row = _fn("outbox", "send")(approval_id)
    except Exception as ex:
        if type(ex).__name__ == "ApprovalInvalidated":
            raise ApprovalBlocked(str(ex)) from ex
        raise
    audit("sent", {"approval_id": approval_id, "kind": card["kind"], "quote_id": card["quote_id"],
                   "recipient": card["recipient"], "status": row.get("status"),
                   "display_status": row.get("display_status")}, actor=REVIEWER)
    return row


def rebuild_card(approval_id) -> dict:
    card = get_card(approval_id)
    if card is None:
        raise ValueError(f"Unknown approval {approval_id}")
    if card["kind"] == "clarification":
        return prepare_clarification(card["provider"])
    return prepare_arrangement(card["provider"])


# ---------------------------------------------------------------------------
# Steps 11–14: reply → Quote v2 → replan → explain
# ---------------------------------------------------------------------------


def ingest_reply(text_or_path: str, provider: str, filename: str | None = None) -> dict:
    import drafting

    provider = provider.strip().upper()
    p = Path(text_or_path) if len(text_or_path) < 400 and "\n" not in text_or_path else None
    if p is not None and p.exists():
        text, filename = read_document(p), filename or p.name
    else:
        text, filename = text_or_path, filename or f"reply_{provider}_pasted_{int(time.time())}.txt"
    old = latest_quotes().get(provider)
    if not old:
        raise ValueError(f"No earlier quote from provider {provider} to update")
    old_qid, n = old["quote_id"], old["version"] + 1
    new_qid = quote_id_for(provider, n)
    v1_items = quote_items(old_qid)
    doc_id = db("insert_document", kind="reply", provider=provider, filename=filename, raw_text=text,
                is_fictional=True, source_url=None)
    reply_items, traces = _extract_and_classify(text, filename, new_qid)
    reply_items, issues = validate_items(reply_items, new_qid, provider, filename)
    _log_traces(traces, reply_items, new_qid)
    merged, changes = merge_reply(v1_items, reply_items, new_qid, provider)
    merged, issues2 = validate_items(merged, new_qid, provider, filename)
    store = [{k: v for k, v in it.items() if k != "v1_item_id"} for it in merged]
    db("insert_quote", provider, n, quote_id=new_qid, supersedes_id=old_qid, document_id=doc_id)
    db("insert_line_items", store)
    db("mark_plans_stale", provider)
    remember("remember_quote", new_qid, provider, n, store, supersedes=old_qid)
    qids = [q for c in approval_cards("clarification") if c.get("quote_id") == old_qid
            for q in (c["extra"].get("question_ids") or [])]
    reply_id = f"R-{new_qid}"
    for qq in dict.fromkeys(qids) or [f"Q-{old_qid}"]:
        remember("remember_reply", reply_id, qq, new_qid, text=text[:2000])
    try:
        rec = recall(f"What was pending with Provider {provider} before this reply?", log=False)
    except ModuleNotReady:
        rec = {"query": None, "answer": "", "nodes": [], "edges": []}
    ws = wishes()
    old_plan = plan_for_quote_any(old_qid)
    if old_plan is None:  # no comparison was run on v1 yet: plan it now, same optimizer
        old_plan = _fn("optimizer", "best_plan")({old_qid: v1_items}, ws)[0]
    new_plan, opt_diff = _fn("optimizer", "replan")(old_plan, v1_items, store, ws)
    if new_plan:
        db("upsert_plan", new_plan, stale=False)
        remember("remember_plan", new_plan)
    rows = line_diff(v1_items, merged)
    diff = {"old_quote_id": old_qid, "new_quote_id": new_qid, "lines": rows,
            "old_plan": _plan_totals(old_plan), "new_plan": _plan_totals(new_plan),
            "optimizer_diff": opt_diff}
    explanation = drafting.explain_change(diff, rec)
    audit("reply_ingested", {"provider": provider, "old_quote_id": old_qid, "new_quote_id": new_qid,
                             "filename": filename, "recipient": find_recipient(text),
                             "changes": [{"kind": c["kind"], "name": c["name"]} for c in changes],
                             "diff": diff, "explanation": explanation,
                             "recall": {"query": rec.get("query"), "answer": rec.get("answer")},
                             "validation_issues": issues + issues2})
    try:
        run_analysis()
    except (ModuleNotReady, ValueError):
        pass
    return {"new_quote_id": new_qid, "old_quote_id": old_qid, "diff": diff, "explanation": explanation,
            "changes": changes, "recall": rec}


def plan_for_quote_any(quote_id: str) -> Optional[dict]:
    cands = [p for p in plans() if p.get("quote_id") == quote_id]
    return cands[-1] if cands else None


def _plan_totals(p: Optional[dict]) -> Optional[dict]:
    if not p:
        return None
    return {k: p.get(k) for k in ("plan_id", "quote_id", "known_total", "estimated_low",
                                  "estimated_high", "unresolved")}


def latest_reply_diff() -> Optional[dict]:
    return last_event("reply_ingested")


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def recall(query: str, exclude_wish_ids: list[str] | None = None, log: bool = True) -> dict:
    res = _call(_fn("memory", "recall"), query, exclude_wish_ids=exclude_wish_ids or None)
    res = dict(res or {})
    res.setdefault("query", query)
    res.setdefault("nodes", [])
    res.setdefault("edges", [])
    if log:
        audit("recall", {"query": query, "exclude_wish_ids": exclude_wish_ids or [], "result": res})
    return res


def last_recall() -> Optional[dict]:
    return last_event("recall")


def graph_snapshot() -> dict:
    return _fn("memory", "graph_snapshot")() or {}


# ---------------------------------------------------------------------------
# Steps 15–18: select, identity, arrangement request
# ---------------------------------------------------------------------------


def select_quote(quote_id: str) -> None:
    audit("selection", {"quote_id": quote_id, "provider": quote_id.rsplit("-v", 1)[0]}, actor=REVIEWER)


def current_selection() -> Optional[dict]:
    return last_event("selection")


def create_persona_inquiry() -> dict:
    res = _fn("persona", "create_inquiry")(reference_id=f"reviewer-{int(time.time())}")
    audit("persona_inquiry_created", {"inquiry_id": res["inquiry_id"], "hosted_url": res.get("hosted_url")})
    return res


def check_persona_status(inquiry_id: str) -> str:
    status = _fn("persona", "get_status")(inquiry_id)
    audit("persona_status", {"inquiry_id": inquiry_id, "status": status})
    return status


def simulate_persona_approval(inquiry_id: str) -> str:
    status = _fn("persona", "simulate_approve")(inquiry_id)
    audit("persona_status", {"inquiry_id": inquiry_id, "status": status, "sandbox_simulated": True})
    return status


def persona_state() -> dict:
    inq = last_event("persona_inquiry_created") or {}
    st = last_event("persona_status", inquiry_id=inq.get("inquiry_id")) if inq else None
    return {**inq, "status": (st or {}).get("status"), "sandbox_simulated": (st or {}).get("sandbox_simulated")}


def plan_services(plan: dict, items: list[dict]) -> list[dict]:
    ids = set(plan.get("items") or [])
    return [it for it in items if it["item_id"] in ids]


def prepare_arrangement(provider: str) -> dict:
    import drafting

    q = latest_quotes().get(provider)
    if not q:
        raise ValueError(f"No quote for provider {provider}")
    qid = q["quote_id"]
    plan = plan_for_quote(qid)
    if not plan:
        raise ValueError(f"No current plan for {qid} — run the comparison first.")
    items = quote_items(qid)
    services = plan_services(plan, items)
    body = drafting.draft_arrangement(plan, services, provider, qid)
    recipient = recipient_for(provider)
    extra = {"provider": provider, "plan_id": plan["plan_id"],
             "services": [{"item_id": s_["item_id"], "name": s_.get("name"), "amount": item_amount_text(s_)}
                          for s_ in services],
             "known_total": plan.get("known_total"), "estimated_low": plan.get("estimated_low"),
             "estimated_high": plan.get("estimated_high"), "unresolved": plan.get("unresolved") or []}
    card = _prepare_card("arrangement", qid, recipient, body, extra)
    audit("arrangement_prepared", {"approval_id": card["approval_id"], "provider": provider, "quote_id": qid,
                                   "plan_id": plan["plan_id"]})
    return card


def evidence_receipt(quote_id: str, plan: dict) -> list[dict]:
    ws = {w["wish_id"]: w for w in wishes()}
    rows = []
    for it in plan_services(plan, quote_items(quote_id)):
        wish_ids = it.get("wish_ids") or plan.get("wishes_satisfied") or []
        rows.append({"service": it.get("name"), "amount": item_amount_text(it), "quote_version": quote_id,
                     "excerpt": it.get("excerpt", ""), "source_doc": it.get("source_doc", ""),
                     "wishes": "; ".join(f"{w}: {ws[w]['text']}" if w in ws else w for w in wish_ids)})
    return rows


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def reset_demo() -> None:
    db("reset_all")
    try:
        _fn("memory", "reset_memory")()
    except ModuleNotReady:
        pass
    audit("reset_demo", {}, actor=REVIEWER)


def payload_hash(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]
