"""Chat engine over agent.py.

ENGINE_NOTES
------------
Public API (signatures fixed, another agent builds chat_app.py against them):
    handle(text, files=None) -> list[dict]   free text and/or files -> events
    act(action: dict)        -> list[dict]   button/chip actions -> events
    history()                -> list[dict]   flat, ordered events incl. {"type": "user", "text": ...}

Events (all JSON-serializable, 'type' key; see chat/events.py):
    text{text} quote{provider,quote_id,version,fictional,source,rows[],known_total,estimated_low,
    estimated_high,unresolved} flags{flags} plan{plan,note} approval{card} diff{diff,explanation}
    memory{query,answer,nodes,edges,backend} next_steps{items:[{label,action}]} receipt{lines,rows?}
    error{message}.  diff is the list of rows [{name,v1,v2,status,...}]; receipt lines are strings.
    approval.card keys: approval_id, kind, provider, quote_id, recipient, body, status, valid, sent
    (display status string or None), extra, identity_note (arrangement only).
    history() refreshes each stored approval card (valid/sent/status) from the DB.

Actions (act): {"do": "load_samples"|"compare"|"draft_clarification"|"approve"|"rebuild"|"select"|
    "prepare_arrangement"|"recall"|"reset", provider|approval_id|quote_id|query}. "load_sample" is an alias.

Behaviour:
  * Everything goes through agent.py. Pasted text is written to .chat_tmp/ so ingest_document(path) works.
  * Quotes A/B/C are labeled fictional. data/real_gpl.pdf is labeled real, with its source taken from
    data/SOURCES.md, and is extracted into its own lane: it is NOT stored as a quote, so it never enters
    the comparison, flags or plans (load_samples include_real=False skips it; extraction can be slow).
  * Persona is skipped in chat mode. agent.approve_and_send requires Persona for arrangements, so the
    engine approves + sends arrangements itself (approvals.approve + outbox.send, same one-message /
    send-once rules) recording persona_inquiry_id="chat-mode-persona-skipped" and the audit note
    "identity verification not run (sandbox chat mode)". Env LW_CHAT_SKIP_PERSONA (default "1"):
    set to 0/false to fall back to agent.approve_and_send (which then blocks without a Persona id).
    The card and receipt always say identity verification was not run. Nothing is ever called verified.
  * Router is rule-based (chat/router.py). URLs: "not available yet" unless chat.fetch exists
    (chat.fetch.fetch_text(url) -> str, if a later module provides it).
  * History: audit_log rows, action 'chat_message' (chat/history.py). No new tables.
  * Unknown prices are 'Unresolved', never $0 and never called cheapest. Flags are review prompts only.
"""
from __future__ import annotations

import importlib
import os
import re
import time
from pathlib import Path
from typing import Any

import agent
from agent import ApprovalBlocked, ModuleNotReady
from chat import events as ev
from chat import history as hist
from chat import router

TMP_DIR = agent.ROOT / ".chat_tmp"
PERSONA_MARKER = "chat-mode-persona-skipped"
IDENTITY_NOTE = "Identity verification not run (sandbox chat mode)."
OPEN_KINDS = ("unresolved_charge", "stated_requirement")
_counter = [0]


def skip_persona() -> bool:
    return os.getenv("LW_CHAT_SKIP_PERSONA", "1").strip().lower() not in ("0", "false", "no", "off")


def _redact(msg: str) -> str:
    return re.sub(r"(\w+://)[^/\s@]+@", r"\1***@", str(msg))


def _ensure() -> None:
    agent.init()


def _tmp(name: str, content: str | bytes) -> Path:
    _counter[0] += 1
    d = TMP_DIR / f"{int(time.time())}_{os.getpid()}_{_counter[0]}"
    d.mkdir(parents=True, exist_ok=True)
    p = d / re.sub(r"[^\w.\-]", "_", name)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Event builders
# ---------------------------------------------------------------------------


def _derive_totals(items: list[dict]) -> tuple[float, float, float | None, list[str]]:
    """Quote-level totals from validated items: fixed -> known; estimated/starting_at -> estimate range
    (high is None when any starting_at item is open-ended); unknown -> listed as unresolved, never summed."""
    known = est_low = est_high_sum = 0.0
    open_ended = False
    unresolved = []
    for it in items:
        pt, lo, hi = it.get("price_type"), it.get("amount_low"), it.get("amount_high")
        if pt == "unknown" or (lo is None and hi is None):
            unresolved.append(f"{it.get('provider')}: {it.get('name')}")
        elif pt == "fixed":
            known += lo or 0.0
        else:
            est_low += lo or 0.0
            if pt == "starting_at" and hi is None:
                open_ended = True
            else:
                est_high_sum += hi if hi is not None else (lo or 0.0)
    return known, est_low, (None if open_ended else est_high_sum), unresolved


def _rows(items: list[dict]) -> list[dict]:
    return [{"name": it.get("name"), "category": it.get("category"), "price_type": it.get("price_type"),
             "amount_text": agent.item_amount_text(it), "excerpt": (it.get("excerpt") or "")[:300]}
            for it in items]


def _quote_event(quote_id: str, items: list[dict] | None = None, fictional: bool = True,
                 source: str | None = None, provider: str | None = None, version: int | None = None) -> dict:
    items = items if items is not None else agent.quote_items(quote_id)
    provider = provider or quote_id.rsplit("-v", 1)[0]
    version = version or int(quote_id.rsplit("-v", 1)[-1])
    known, lo, hi, unresolved = _derive_totals(items)
    src = source or next((i.get("source_doc") for i in items if i.get("source_doc")), None)
    if fictional and src:
        src = f"{src} (fictional sample)"
    return ev.quote(provider, quote_id, version, fictional, src, _rows(items), known, lo, hi, unresolved)


def _flags_event() -> dict | None:
    out = []
    for q in agent.latest_quotes().values():
        out.extend(agent.flags(q["quote_id"]))
    return ev.flags(out) if out else None


def _plan_event(plan: dict | None, note_extra: str = "") -> dict | None:
    if not plan:
        return None
    qid = plan.get("quote_id") or ""
    items = {i["item_id"]: i for i in agent.quote_items(qid)} if qid else {}
    p = dict(plan)
    p["provider"] = qid.rsplit("-v", 1)[0] if qid else None
    p["services"] = [{"name": items[i].get("name"), "amount_text": agent.item_amount_text(items[i])}
                     for i in plan.get("items") or [] if i in items]
    nn = []
    for n in plan.get("not_needed") or []:
        n = dict(n)
        n["name"] = (items.get(n.get("item_id")) or {}).get("name")
        n["savings_text"] = "Unresolved" if n.get("savings") is None else agent.fmt_money(n["savings"])
        nn.append(n)
    p["not_needed"] = nn
    notes = []
    if plan.get("unresolved"):
        notes.append("This plan still has unresolved charges (" + "; ".join(plan["unresolved"]) +
                     "). They are not counted as $0, so no total here is a ceiling and this plan is not "
                     "ranked as lowest.")
    notes += list(plan.get("notes") or [])
    if note_extra:
        notes.append(note_extra)
    return ev.plan(p, " ".join(notes))


def _card_dict(c: dict) -> dict:
    sent = c.get("sent")
    d = {"approval_id": c["approval_id"], "kind": c.get("kind"), "provider": c.get("provider"),
         "quote_id": c.get("quote_id"), "recipient": c.get("recipient"), "body": c.get("body"),
         "status": c.get("status"), "valid": bool(c.get("valid")),
         "sent": (sent.get("display_status") or "sent") if sent else None,
         "extra": c.get("extra") or {}}
    if c.get("kind") == "arrangement" and skip_persona():
        d["identity_note"] = IDENTITY_NOTE
    return d


def _approval_event(card: dict) -> dict:
    live = agent.get_card(card["approval_id"]) or card
    return ev.approval(_card_dict(live))


# ---------------------------------------------------------------------------
# State -> next-step chips
# ---------------------------------------------------------------------------


def _subject(flag: dict, items: dict) -> str:
    import drafting

    it = items.get(flag.get("item_id")) or {}
    return (it.get("name") or drafting.flag_subject(flag)).strip().lower()


def _next_steps(extra_first: list[dict] | None = None) -> dict | None:
    chips: list[dict] = list(extra_first or [])
    latest = agent.latest_quotes()
    has_wishes = bool(agent.wishes())
    if not latest and not has_wishes:
        chips.append({"label": "Load the sample documents", "action": {"do": "load_samples"}})
    elif not latest:
        chips.append({"label": "Load the sample quotes", "action": {"do": "load_samples"}})
    cards = agent.approval_cards()
    for prov, q in latest.items():
        qid = q["quote_id"]
        mine = [c for c in cards if c.get("quote_id") == qid and c.get("kind") == "clarification"]
        pending = [c for c in mine if c["valid"] and not c.get("sent")]
        if pending:
            chips.append({"label": f"Approve and send the message to Provider {prov}",
                          "action": {"do": "approve", "approval_id": pending[-1]["approval_id"]}})
            continue
        if any(c.get("sent") for c in mine):
            continue
        fl = [f for f in agent.flags(qid) if f.get("kind") in OPEN_KINDS]
        if fl:
            items = {i["item_id"]: i for i in agent.quote_items(qid)}
            unresolved = [f for f in fl if f.get("kind") == "unresolved_charge"]
            label = (f"Ask Provider {prov} about the {_subject(unresolved[0], items)}" if unresolved
                     else f"Ask Provider {prov} to clarify a stated requirement")
            chips.append({"label": label, "action": {"do": "draft_clarification", "provider": prov}})
    if latest and has_wishes:
        chips.append({"label": "Compare quotes", "action": {"do": "compare"}})
        cp = agent.chosen_plan()
        if cp:
            prov = cp["quote_id"].rsplit("-v", 1)[0]
            arr = [c for c in cards if c.get("kind") == "arrangement" and c.get("quote_id") == cp["quote_id"]]
            pend = [c for c in arr if c["valid"] and not c.get("sent")]
            if pend:
                chips.append({"label": f"Approve the arrangement request to Provider {prov}",
                              "action": {"do": "approve", "approval_id": pend[-1]["approval_id"]}})
            elif not any(c.get("sent") for c in arr):
                chips.append({"label": "Prepare the request", "action": {"do": "prepare_arrangement",
                                                                         "provider": prov}})
    if has_wishes:
        chips.append({"label": "What do we remember about the wishes?",
                      "action": {"do": "recall", "query": "What did the family want, and what is still pending?"}})
    return ev.next_steps(chips[:6]) if chips else None


def _finish(events: list[dict], steps: bool = True) -> list[dict]:
    events = [e for e in events if e]
    if steps and not any(e["type"] == "next_steps" for e in events):
        try:
            ns = _next_steps()
        except Exception:
            ns = None
        if ns:
            events.append(ns)
    return events


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def _sources_real() -> tuple[str, str | None]:
    """Label and URL for data/real_gpl.pdf from data/SOURCES.md."""
    try:
        for line in (agent.DATA_DIR / "SOURCES.md").read_text(encoding="utf-8").splitlines():
            if "real_gpl.pdf" in line:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                m = re.search(r"\((.+?)\)", cells[1] if len(cells) > 1 else "")
                link = re.search(r"\[[^\]]+\]\((https?://[^)]+)\)", line)
                who = m.group(1) if m else "public price list"
                url = link.group(1) if link else None
                return f"Real public price list: {who}" + (f" — {url}" if url else ""), url
    except OSError:
        pass
    return "Real public price list (see data/SOURCES.md)", None


def _ingest_real(path: Path, source: str, url: str | None) -> dict:
    """Separate lane: extract and show, never store as a quote (keeps it out of the comparison)."""
    text = agent.read_document(path)
    agent.db("insert_document", kind="real_price_list", provider="REAL", filename=path.name, raw_text=text,
             is_fictional=False, source_url=url)
    items, traces = agent._extract_and_classify(text, path.name, "REAL-v1")
    items, _ = agent.validate_items(items, "REAL-v1", "REAL", path.name)
    agent._log_traces(traces, items, "REAL-v1")
    e = _quote_event("REAL-v1", items=items, fictional=False, source=source, provider="REAL", version=1)
    e["note"] = "Shown for reference only. It is not part of the comparison."
    return e


def _analysis_events(note: str = "") -> list[dict]:
    res = agent.run_analysis()
    return [e for e in (_flags_event(), _plan_event(res.get("plan"), note)) if e]


def _can_analyze() -> bool:
    return bool(agent.latest_quotes()) and bool(agent.wishes())


def _wishes_text() -> str:
    ws = agent.wishes()
    lines = [f"- {w['wish_id']}: {w['text']}" for w in ws]
    return "Here is what I understood of the wishes:\n" + "\n".join(lines)


def _load_samples(include_real: bool = True) -> list[dict]:
    out: list[dict] = []
    if agent.wishes() and agent.latest_quotes():
        out.append(ev.text("The sample documents are already loaded. I re-ran the comparison."))
    else:
        if not agent.wishes():
            agent.ingest_wishes()
            out.append(ev.text(_wishes_text()))
        for p in sorted(agent.DATA_DIR.glob("quote_*.txt")):
            prov = agent.provider_from_filename(p.name)
            if prov and prov not in agent.latest_quotes():
                res = agent.ingest_document(p, provider=prov, is_fictional=True)
                out.append(_quote_event(res["quote_id"], res["items"]))
    if _can_analyze():
        out += _analysis_events()
    if include_real:
        real = agent.DATA_DIR / "real_gpl.pdf"
        if real.exists():
            src, url = _sources_real()
            try:
                out.append(_ingest_real(real, src, url))
            except Exception as ex:
                out.append(ev.error(f"The real price list could not be read: {_redact(ex)}"))
    return out


def _compare() -> list[dict]:
    if not agent.latest_quotes():
        return [ev.text("There are no quotes yet. Paste a quote, drop in a file, or load the sample documents.")]
    if not agent.wishes():
        return [ev.text("I need the wishes first. Paste what she wanted, or load the sample documents.")]
    res = agent.run_analysis()
    lines = []
    complete = []
    for prov, q in agent.latest_quotes().items():
        p = agent.plan_for_quote(q["quote_id"])
        if not p:
            lines.append(f"- Provider {prov}: no plan could be built.")
            continue
        est = agent.fmt_money(p.get("estimated_low"), p.get("estimated_high"),
                              None if p.get("estimated_high") is not None else "starting_at")
        unres = p.get("unresolved") or []
        lines.append(f"- Provider {prov} ({q['quote_id']}): known charges {agent.fmt_money(p.get('known_total'))}, "
                     f"estimated {est}, {len(unres)} unresolved" + (" (" + "; ".join(unres) + ")" if unres else ""))
        if not unres and p.get("estimated_high") is not None:
            complete.append((p["known_total"] + p["estimated_high"], prov))
    head = "Here is how the quotes compare for what the family asked for."
    if complete:
        complete.sort()
        tail = (f"Among plans with no unresolved charges, Provider {complete[0][1]} has the lowest total. "
                "Plans with an unresolved charge cannot be ranked yet.")
    else:
        tail = "No plan is fully priced yet, so I am not ranking them. Unresolved charges are never counted as $0."
    out = [ev.text(head + "\n" + "\n".join(lines) + "\n" + tail)]
    out += [e for e in (_flags_event(), _plan_event(res.get("plan"))) if e]
    return out


def _draft_clarification(provider: str) -> list[dict]:
    provider = (provider or "").strip().upper()
    try:
        card = agent.prepare_clarification(provider)
    except ValueError as ex:
        return [ev.text(f"{ex}. Nothing to ask Provider {provider} right now.")]
    return [ev.text(f"I drafted one message to Provider {provider}. It asks only about what is open. "
                    "Nothing is sent until you approve it."), _approval_event(card)]


def _arrangement_send(card: dict) -> dict:
    """Chat-mode send: no Persona, same one-message / send-once rules as agent.approve_and_send."""
    import approvals
    import outbox

    if card.get("sent"):
        return card["sent"]
    if not card["valid"]:
        raise ApprovalBlocked("This approval was invalidated because the quote changed. Rebuild the card.")
    try:
        if card.get("status") == "pending":
            approvals.approve(card["approval_id"], agent.REVIEWER, PERSONA_MARKER)
        row = outbox.send(card["approval_id"])
    except Exception as ex:
        if type(ex).__name__ == "ApprovalInvalidated":
            raise ApprovalBlocked(str(ex)) from ex
        raise
    agent.audit("sent", {"approval_id": card["approval_id"], "kind": card["kind"], "quote_id": card["quote_id"],
                         "recipient": card["recipient"], "status": row.get("status"),
                         "display_status": row.get("display_status"),
                         "identity": "verification not run (sandbox chat mode)"}, actor=agent.REVIEWER)
    return row


def _receipt_events(card: dict, row: dict) -> list[dict]:
    status = row.get("display_status") or "sent"
    lines = [status, f"To: {card['recipient']} (sandbox outbox, nothing left this computer)",
             f"Quote version: {card['quote_id']}"]
    rows: list[dict] = []
    if card["kind"] == "arrangement":
        lines.append(IDENTITY_NOTE if skip_persona() else "Identity check: see Persona record.")
        plan = next((p for p in agent.plans() if p.get("plan_id") == (card.get("extra") or {}).get("plan_id")), None)
        if plan:
            rows = agent.evidence_receipt(card["quote_id"], plan)
            for r in rows:
                lines.append(f"{r['service']}: {r['amount']} ({r['quote_version']}) — \"{r['excerpt']}\"")
        unres = (card.get("extra") or {}).get("unresolved") or []
        if unres:
            lines.append("Still unresolved: " + "; ".join(unres))
    return [ev.text(status), ev.receipt(lines, rows)]


def _approve(approval_id) -> list[dict]:
    card = agent.get_card(approval_id)
    if card is None:
        return [ev.error("I could not find that approval.")]
    if card.get("sent"):
        return [ev.text("That message was already sent. I did not send it again.")]
    if not card["valid"]:
        return [ev.error("This approval no longer matches the latest quote, so it cannot be sent. "
                         "Rebuild the card to review the updated message."), _approval_event(card)]
    if card["kind"] == "arrangement" and skip_persona():
        row = _arrangement_send(card)
    else:
        row = agent.approve_and_send(approval_id)
    return _receipt_events(card, row)


def _rebuild(approval_id) -> list[dict]:
    try:
        card = agent.rebuild_card(approval_id)
    except ValueError as ex:
        return [ev.text(f"Nothing to rebuild: {ex}. The latest quote may already answer the open questions.")]
    return [ev.text("I rebuilt the message from the latest quote. Review it before approving."),
            _approval_event(card)]


def _select(quote_id: str) -> list[dict]:
    agent.select_quote(quote_id)
    return [ev.text(f"Selected {quote_id}. I will use this quote for the arrangement request.")]


def _prepare_arrangement(provider: str | None) -> list[dict]:
    prov = (provider or "").strip().upper()
    if not prov:
        cp = agent.chosen_plan()
        if not cp:
            return [ev.text("Compare the quotes first so I know which plan to request.")]
        prov = cp["quote_id"].rsplit("-v", 1)[0]
    q = agent.latest_quotes().get(prov)
    if q and not agent.plan_for_quote(q["quote_id"]) and _can_analyze():
        agent.run_analysis()
    card = agent.prepare_arrangement(prov)
    out = [ev.text(f"I drafted the arrangement request to Provider {prov}. It is a request, not a payment, "
                   "and nothing is sent until you approve it. " + (IDENTITY_NOTE if skip_persona() else ""))]
    unres = (card.get("extra") or {}).get("unresolved") or []
    if unres:
        out.append(ev.text("Note: this request still has unresolved charges (" + "; ".join(unres) +
                           "). They are not counted as $0."))
    out.append(_approval_event(card))
    return out


def _recall(query: str | None) -> list[dict]:
    q = query or "What did the family want, and what is still pending?"
    try:
        res = agent.recall(q)
    except ModuleNotReady:
        return [ev.text("Memory is not available right now. The database is still the record of every quote.")]
    return [_memory_event(res)]


def _memory_event(res: dict) -> dict:
    backend = res.get("backend") or (res.get("meta") or {}).get("backend") or (
        "cognee" if "excluded_wish_ids" in res else "memory")
    return ev.memory(res.get("query"), res.get("answer") or "", res.get("nodes") or [], res.get("edges") or [],
                     backend)


def _reset() -> list[dict]:
    agent.reset_demo()
    return [ev.text("Everything is cleared. Start by pasting what she wanted, or load the sample documents.")]


# ---------------------------------------------------------------------------
# Free text and files
# ---------------------------------------------------------------------------


def _free_provider() -> str:
    used = set(agent.latest_quotes())
    for i in range(26):
        c = chr(ord("A") + i)
        if c not in used:
            return c
    return "Z"


def _infer_reply_provider(text: str) -> str | None:
    """Provider of a pasted reply: sender address matches a stored recipient, else the only candidate."""
    sender = router.sender_email(text)
    latest = agent.latest_quotes()
    if sender:
        for prov in latest:
            if (agent.recipient_for(prov) or "").lower() == sender.lower():
                return prov
    waiting = [c["provider"] for c in agent.approval_cards("clarification") if c.get("sent")]
    waiting = list(dict.fromkeys(p for p in waiting if p in latest))
    if len(waiting) == 1:
        return waiting[0]
    if len(latest) == 1:
        return next(iter(latest))
    return None


def _do_wishes(path: Path) -> list[dict]:
    before = {w["wish_id"] for w in agent.wishes()}
    merged = agent.ingest_wishes([path])
    if not merged:
        return [ev.text("I could not find any wishes in that text. Try describing what she wanted in a few "
                        "plain sentences.")]
    new = [w for w in agent.wishes() if w["wish_id"] not in before]
    out = [ev.text(_wishes_text() + ("" if new else "\n(No new wishes beyond those already saved.)"))]
    if _can_analyze():
        out += _analysis_events()
    return out


def _do_quote(path: Path, provider: str | None, fictional: bool = False) -> list[dict]:
    prov = provider or agent.provider_from_filename(path.name) or _free_provider()
    if prov in agent.latest_quotes():
        return [ev.text(f"Provider {prov} already has a quote. If this is their reply, say "
                        f"\"reply from {prov}:\" and paste it. I keep every version.")]
    res = agent.ingest_document(path, provider=prov, is_fictional=fictional)
    out = [ev.text(f"Read the quote as Provider {prov} ({res['quote_id']}): {len(res['items'])} lines."),
           _quote_event(res["quote_id"], res["items"], fictional=fictional)]
    if _can_analyze():
        out += _analysis_events()
    else:
        out.append(ev.text("I will compare once I also have the wishes."))
    return out


def _do_reply(text_or_path: str, provider: str | None) -> list[dict]:
    prov = (provider or "").upper() or _infer_reply_provider(text_or_path)
    if not prov:
        return [ev.text("I could not tell which provider this reply is from. Start the message with "
                        "\"reply from A:\" (or B, C).")]
    if prov not in agent.latest_quotes():
        return [ev.text(f"I have no earlier quote from Provider {prov}, so there is nothing to update.")]
    res = agent.ingest_reply(text_or_path, prov)
    out = [ev.text(f"Provider {prov} replied. I saved {res['new_quote_id']} and kept {res['old_quote_id']} "
                   "unchanged."),
           _quote_event(res["new_quote_id"]),
           ev.diff(res["diff"]["lines"], res["explanation"])]
    rec = res.get("recall") or {}
    if rec.get("answer") or rec.get("nodes"):
        out.append(_memory_event(rec))
    np_ = agent.plan_for_quote(res["new_quote_id"])
    out += [e for e in (_flags_event(), _plan_event(np_)) if e]
    return out


def _fetch_module():
    try:
        return importlib.import_module("chat.fetch")
    except ImportError:
        return None


def _do_url(urls: list[str]) -> list[dict]:
    fm = _fetch_module()
    if fm is None or not hasattr(fm, "fetch_text"):
        return [ev.text("Fetching web pages is not available yet. Please paste the text of the page or upload "
                        "the file instead.")]
    out: list[dict] = []
    for u in urls[:2]:
        out += handle_text(fm.fetch_text(u))
    return out


def _help() -> list[dict]:
    return [ev.text("I can read what she wanted, read provider quotes, compare them, and draft messages for "
                    "you to approve. Paste text, drop in a file, or use a suggestion below. To add a provider's "
                    "reply, start with \"reply from A:\".")]


def handle_text(text: str) -> list[dict]:
    r = router.route(text)
    intent = r["intent"]
    if intent == "url":
        return _do_url(r["urls"])
    if intent == "compare":
        return _compare()
    if intent == "recall":
        return _recall(text)
    if intent == "reset_hint":
        return [ev.text("To clear everything, use the Reset button. I will not do it from a typed message.")]
    if intent == "approve_hint":
        return [ev.text("Use the Approve button on the message card. Each approval covers exactly one message.")]
    if intent == "wishes":
        return _do_wishes(_tmp("wishes_pasted.txt", r["body"]))
    if intent == "quote":
        prov = r["provider"] or _free_provider()
        return _do_quote(_tmp(f"quote_{prov}_pasted.txt", r["body"]), prov)
    if intent == "reply":
        return _do_reply(r["body"], r["provider"])
    return _help()


def _file_parts(f: Any) -> tuple[str, Path | None, bytes | None]:
    """(name, existing path | None, content bytes | None) for a path, dict, tuple or upload object."""
    if isinstance(f, (str, Path)):
        return Path(f).name, Path(f), None
    if isinstance(f, dict):
        if f.get("path"):
            return f.get("name") or Path(f["path"]).name, Path(f["path"]), None
        c = f.get("bytes") if f.get("bytes") is not None else f.get("text", f.get("content", b""))
        return f.get("name", "upload.txt"), None, c.encode() if isinstance(c, str) else c
    if isinstance(f, tuple) and len(f) == 2:
        c = f[1]
        return str(f[0]), None, c.encode() if isinstance(c, str) else c
    name = getattr(f, "name", "upload.txt")
    data = f.getvalue() if hasattr(f, "getvalue") else f.read()
    return name, None, data


def _handle_file(f: Any) -> list[dict]:
    name, path, data = _file_parts(f)
    if path is None or not path.exists():
        path = _tmp(name, data or b"")
    low = name.lower()
    stem = Path(name).stem.lower()
    if low.endswith(".pdf"):
        src = "Uploaded PDF (real document, shown separately from the fictional comparison)"
        e = _ingest_real(path, src, None)
        return [ev.text(f"Read {name} as a real price list. I show it on its own and do not mix it into the "
                        "comparison."), e]
    if stem.startswith(("wish", "confirmation", "note")):
        return _do_wishes(path)
    prov = agent.provider_from_filename(name)
    if stem.startswith("reply"):
        return _do_reply(str(path) if len(str(path)) < 400 else agent.read_document(path), prov)
    if stem.startswith(("quote", "gpl", "price")):
        return _do_quote(path, prov)
    # unknown name: sniff the content
    r = router.route(agent.read_document(path))
    if r["intent"] == "reply":
        return _do_reply(agent.read_document(path), r["provider"])
    if r["intent"] == "quote":
        return _do_quote(path, r["provider"])
    if r["intent"] == "wishes":
        return _do_wishes(path)
    return [ev.text(f"I could not tell what {name} is. Name it quote_A, reply_A or wishes, or paste the text "
                    "with a prefix such as \"quote from B:\".")]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _guard(fn) -> list[dict]:
    try:
        return fn()
    except ModuleNotReady as e:
        return [ev.error(f"Module not ready: {e.module}. That step will work once it is available.")]
    except ApprovalBlocked as e:
        return [ev.error(_redact(e))]
    except ValueError as e:
        return [ev.error(_redact(e))]
    except Exception as e:  # keep the chat alive
        return [ev.error(f"That step could not complete ({type(e).__name__}): {_redact(e)}")]


def handle(text: str, files: list | None = None) -> list[dict]:
    """Free text and/or files in, events out. History is stored."""
    _ensure()
    names = []
    for f in files or []:
        try:
            names.append(_file_parts(f)[0])
        except Exception:
            names.append("file")
    user = ev.user(text or "", names)
    out: list[dict] = []
    for f in files or []:
        out += _guard(lambda f=f: _handle_file(f))
    if (text or "").strip() or not files:
        out += _guard(lambda: handle_text(text or ""))
    out = _finish(out)
    hist.record("user", [user])
    hist.record("agent", out)
    return out


def act(action: dict) -> list[dict]:
    """Button/chip actions. History is stored."""
    _ensure()
    action = dict(action or {})
    do = action.get("do")
    labels = {"load_samples": "Load sample documents", "load_sample": "Load sample documents",
              "compare": "Compare quotes", "draft_clarification": f"Ask Provider {action.get('provider', '')}",
              "approve": "Approve", "rebuild": "Rebuild message", "select": "Select quote",
              "prepare_arrangement": "Prepare the request", "recall": "What do we remember?", "reset": "Reset"}
    user = ev.user(labels.get(do, str(do)), action=action)
    handlers = {
        "load_samples": lambda: _load_samples(action.get("include_real", True)),
        "load_sample": lambda: _load_samples(action.get("include_real", True)),
        "compare": _compare,
        "draft_clarification": lambda: _draft_clarification(action.get("provider")),
        "approve": lambda: _approve(action.get("approval_id")),
        "rebuild": lambda: _rebuild(action.get("approval_id")),
        "select": lambda: _select(action.get("quote_id")),
        "prepare_arrangement": lambda: _prepare_arrangement(action.get("provider")),
        "recall": lambda: _recall(action.get("query")),
        "reset": _reset,
    }
    h = handlers.get(do)
    out = _guard(h) if h else [ev.error(f"I do not know how to do '{do}'.")]
    out = _finish(out)
    if do == "reset":  # reset wipes the audit log: history restarts from here
        hist.record("agent", out)
    else:
        hist.record("user", [user])
        hist.record("agent", out)
    return out


def history() -> list[dict]:
    """Flat ordered events (user messages are {'type': 'user'}); approval cards show live state."""
    _ensure()
    events = hist.load()
    try:
        live = {c["approval_id"]: c for c in agent.approval_cards()}
    except Exception:
        live = {}
    for e in events:
        if e.get("type") == "approval" and e["card"].get("approval_id") in live:
            e["card"].update({k: v for k, v in _card_dict(live[e["card"]["approval_id"]]).items()
                              if k in ("valid", "sent", "status")})
    return events
