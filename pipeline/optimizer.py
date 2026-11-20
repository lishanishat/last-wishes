"""Itemized-plan optimizer and replan (LAST_WISHES.md §8 steps 8 and 14).

Pure Python, no LLM. Unknown is never zero: unknown prices go to `unresolved`,
and a plan with anything unresolved is never ranked above a fully known plan.
"""
from __future__ import annotations

import itertools
import math
import re
from typing import Optional

from contracts import LineItem, NotNeeded, Plan
from pipeline.wishes import (
    Wish,
    conflicting_wishes,
    covers_crematory_fee,
    extra_kind,
    has_known_price,
    is_cremation_service,
    is_viewing,
    offers_cremation,
    wish_by_kind,
)

MAX_BRUTE_FORCE = 16  # optional items enumerated exhaustively up to this many
MISSING_CREMATORY = "crematory fee"


# ---- helpers ---------------------------------------------------------------

def _provider(items: list[LineItem], quote_id: str) -> str:
    if items and items[0].get("provider"):
        return items[0]["provider"]
    return quote_id.split("-")[0]


def _cost_parts(items: list[LineItem]) -> tuple[float, float, Optional[float], list[LineItem]]:
    """(known_total, estimated_low, estimated_high, unknown_items)."""
    known = 0.0
    est_low = 0.0
    est_high: Optional[float] = 0.0
    unknown: list[LineItem] = []
    for it in items:
        lo, hi, pt = it.get("amount_low"), it.get("amount_high"), it.get("price_type")
        if pt == "unknown" or (lo is None and hi is None):
            unknown.append(it)
        elif pt == "fixed":
            known += float(lo if lo is not None else hi)
        elif pt == "estimated":
            lo_v = float(lo if lo is not None else hi)
            hi_v = float(hi if hi is not None else lo)
            est_low += lo_v
            if est_high is not None:
                est_high += hi_v
        elif pt == "starting_at":
            est_low += float(lo if lo is not None else hi)
            if hi is None:
                est_high = None  # open-ended
            elif est_high is not None:
                est_high += float(hi)
        else:  # unrecognised price type: treat as unknown, never zero
            unknown.append(it)
    return known, est_low, est_high, unknown


def item_savings(item: LineItem) -> Optional[float]:
    """Conservative savings from dropping an item (low end). None if price unknown."""
    if not has_known_price(item):
        return None
    lo, hi = item.get("amount_low"), item.get("amount_high")
    return float(lo if lo is not None else hi)


def _removable(item: LineItem) -> bool:
    """Optional items can be declined. Package items can be declined only if itemized
    with a known price; basic fees, cash advances and stated requirements stay
    (stated requirements are flagged, never auto-removed)."""
    cat = item.get("category")
    if cat == "optional":
        return True
    if cat == "package":
        return has_known_price(item)
    return False


def _wishes_met(chosen: list[LineItem], all_items: list[LineItem], wishes: list[Wish],
                unresolved: list[str], known: float, est_high: Optional[float]) -> list[str]:
    met: list[str] = []
    for w in wishes:
        k = w["kind"]
        if k == "cremation":
            ok = any(is_cremation_service(i) for i in chosen)
        elif k == "no_viewing":
            ok = not any(is_viewing(i) for i in chosen)
        elif k == "avoid_extras":
            ok = not any(extra_kind(i) for i in chosen)
        elif k == "budget":
            ok = budget_status_parts(w.get("value"), known, est_high, unresolved) == "within"
        else:
            ok = True
        if ok:
            met.append(w["wish_id"])
    return met


def budget_status_parts(budget: Optional[float], known: float, est_high: Optional[float],
                        unresolved: list[str], est_low: float = 0.0) -> str:
    if budget is None:
        return "unknown"
    if known + est_low > budget:
        return "over"
    if unresolved or est_high is None:
        return "unknown"
    return "within" if known + est_high <= budget else "unknown"


def budget_status(plan: Plan, wishes: list[Wish]) -> str:
    """'within' | 'over' | 'unknown'. Never 'within' while anything is unresolved."""
    w = wish_by_kind(wishes, "budget")
    return budget_status_parts(w["value"] if w else None, plan["known_total"],
                               plan["estimated_high"], plan["unresolved"], plan["estimated_low"])


def missing_essentials(items: list[LineItem]) -> list[str]:
    """Essential services for cremation that the quote does not price.

    A quote that offers cremation must price the crematory charge: either an item
    named crematory fee with a known price, or a priced item that states it
    includes the crematory. Otherwise 'crematory fee' is missing.
    """
    if not offers_cremation(items):
        return []
    if any(covers_crematory_fee(i) for i in items):
        return []
    return [MISSING_CREMATORY]


# ---- planning --------------------------------------------------------------

def plan_for_quote(quote_id: str, items: list[LineItem], wishes: list[Wish]) -> Plan:
    """Cheapest itemized set from one quote that meets every wish it can."""
    provider = _provider(items, quote_id)
    fixed_in: list[LineItem] = []      # must stay
    candidates: list[LineItem] = []    # optional, may be added
    excluded_conflicts: list[LineItem] = []

    for it in items:
        conflicts = conflicting_wishes(it, wishes)
        if _removable(it):
            if conflicts:
                excluded_conflicts.append(it)
            else:
                candidates.append(it)
        else:
            fixed_in.append(it)

    def evaluate(chosen: list[LineItem]):
        known, lo, hi, unk = _cost_parts(chosen)
        unresolved = [f"{provider}: {i['name']}" for i in unk]
        unresolved += [f"{provider}: {m}" for m in missing_essentials(items)]
        met = _wishes_met(chosen, items, wishes, unresolved, known, hi)
        core_unmet = sum(1 for w in wishes if w["kind"] != "budget" and w["wish_id"] not in met)
        key = (core_unmet, len(unresolved), known + lo, hi if hi is not None else math.inf, len(chosen))
        return key, (known, lo, hi, unresolved, met)

    # Brute force over optional candidates (small at this scale); greedy fallback.
    if len(candidates) <= MAX_BRUTE_FORCE:
        subsets = itertools.chain.from_iterable(
            itertools.combinations(candidates, r) for r in range(len(candidates) + 1))
    else:
        subsets = iter([(), tuple(c for c in candidates if is_cremation_service(c))])
    best_key, best_chosen, best_vals = None, None, None
    for sub in subsets:
        chosen = fixed_in + list(sub)
        key, vals = evaluate(chosen)
        if best_key is None or key < best_key:
            best_key, best_chosen, best_vals = key, chosen, vals
    assert best_chosen is not None and best_vals is not None
    known, lo, hi, unresolved, met = best_vals

    chosen_ids = {i["item_id"] for i in best_chosen}
    not_needed: list[NotNeeded] = []
    for it in items:
        if it["item_id"] in chosen_ids:
            continue
        s = item_savings(it)
        if s is not None:  # unknown savings are never reported as a number
            not_needed.append({"item_id": it["item_id"], "savings": s})

    return {
        "plan_id": f"plan-{quote_id}",
        "quote_id": quote_id,
        "items": [i["item_id"] for i in items if i["item_id"] in chosen_ids],
        "known_total": round(known, 2),
        "estimated_low": round(lo, 2),
        "estimated_high": None if hi is None else round(hi, 2),
        "unresolved": unresolved,
        "not_needed": not_needed,
        "wishes_satisfied": met,
    }


def plan_rank_key(plan: Plan, wishes: list[Wish]):
    """Fully resolved plans first, then most core wishes met, then cheapest."""
    core = [w["wish_id"] for w in wishes if w["kind"] != "budget"]
    unmet = sum(1 for wid in core if wid not in plan["wishes_satisfied"])
    hi = plan["estimated_high"]
    return (
        1 if plan["unresolved"] else 0,
        unmet,
        plan["known_total"] + plan["estimated_low"],
        math.inf if hi is None else plan["known_total"] + hi,
        plan["quote_id"],
    )


def best_plan(quotes: dict[str, list[LineItem]], wishes: list[Wish]) -> tuple[Plan, list[Plan]]:
    """Return (chosen plan, per-quote plans sorted best-first) for the Compare table.

    A plan with unresolved items is never chosen over a fully known one.
    """
    if not quotes:
        raise ValueError("best_plan needs at least one quote")
    plans = [plan_for_quote(qid, items, wishes) for qid, items in quotes.items()]
    plans.sort(key=lambda p: plan_rank_key(p, wishes))
    return plans[0], plans


def plan_notes(plan: Plan, items: list[LineItem], wishes: list[Wish]) -> list[str]:
    """Plain-language notes for things kept that conflict with wishes (e.g. a package
    item that cannot be removed, or a stated requirement under review)."""
    notes: list[str] = []
    by_id = {i["item_id"]: i for i in items}
    for iid in plan["items"]:
        it = by_id.get(iid)
        if not it:
            continue
        conflicts = conflicting_wishes(it, wishes)
        if it.get("category") == "stated_requirement":
            notes.append(f"{it['name']} is kept pending the provider's clarification of this stated requirement.")
        elif conflicts:
            notes.append(f"{it['name']} is part of a package and has no separate price, so it cannot be removed "
                         f"(conflicts with {', '.join(conflicts)}).")
    return notes


# ---- replan ----------------------------------------------------------------

_STOP = {"the", "a", "an", "of", "and", "for", "fee", "fees", "charge", "charges", "cost",
         "service", "services", "price", "basic", "s"}
_SYNONYMS = {"crematorium": "crematory", "cremation": "cremat", "crematory": "crematory",
             "cremate": "cremat", "visitation": "viewing", "flower": "flowers", "floral": "flowers"}


def _tokens(name: str) -> set[str]:
    toks = re.findall(r"[a-z]+", (name or "").lower())
    out = set()
    for t in toks:
        if t in _STOP:
            continue
        if t.endswith("s") and len(t) > 3 and t[:-1] in _SYNONYMS:
            t = t[:-1]
        out.add(_SYNONYMS.get(t, t))
    if not out:  # names made only of stopwords, e.g. "Service fee"
        out = {t for t in toks}
    return out


def name_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def match_items(old_items: list[LineItem], new_items: list[LineItem],
                threshold: float = 0.5) -> list[tuple[LineItem, LineItem]]:
    """Greedy one-to-one match by normalized-name token overlap (not by item_id)."""
    pairs = []
    for o in old_items:
        for n in new_items:
            s = name_similarity(o["name"], n["name"])
            if s >= threshold:
                pairs.append((s, o, n))
    pairs.sort(key=lambda p: -p[0])
    used_o, used_n, out = set(), set(), []
    for _, o, n in pairs:
        if id(o) in used_o or id(n) in used_n:
            continue
        used_o.add(id(o)); used_n.add(id(n))
        out.append((o, n))
    return out


def merge_quote(old_items: list[LineItem], reply_items: list[LineItem], new_quote_id: str) -> list[LineItem]:
    """Build quote v2 from v1 plus a (possibly partial) reply: matched items are
    replaced, new ones added, the rest carried over. v1 is not modified.
    Item IDs are reissued as f"{new_quote_id}-NN"."""
    matched = {id(o): n for o, n in match_items(old_items, reply_items)}
    matched_new = {id(n) for n in matched.values()}
    merged: list[LineItem] = []
    for o in old_items:
        merged.append(dict(matched.get(id(o), o)))  # type: ignore[arg-type]
    for n in reply_items:
        if id(n) not in matched_new:
            merged.append(dict(n))  # type: ignore[arg-type]
    for i, it in enumerate(merged, 1):
        it["quote_id"] = new_quote_id
        it["item_id"] = f"{new_quote_id}-{i:02d}"
    return merged  # type: ignore[return-value]


def _totals(p: Plan) -> dict:
    return {"known_total": p["known_total"], "estimated_low": p["estimated_low"],
            "estimated_high": p["estimated_high"], "unresolved": list(p["unresolved"])}


def replan(old_plan: Plan, old_items: list[LineItem], new_items: list[LineItem],
           wishes: list[Wish]) -> tuple[Plan, dict]:
    """Re-run the optimizer on the new quote version and diff it against the old one.

    `new_items` is the full new version (use merge_quote for a partial reply).
    """
    new_qid = new_items[0]["quote_id"] if new_items else old_plan["quote_id"]
    new_plan = plan_for_quote(new_qid, new_items, wishes)

    pairs = match_items(old_items, new_items)
    m_old = {id(o) for o, _ in pairs}
    m_new = {id(n) for _, n in pairs}
    changed = []
    resolved: list[str] = []
    for o, n in pairs:
        if (o.get("amount_low"), o.get("amount_high"), o.get("price_type")) != \
           (n.get("amount_low"), n.get("amount_high"), n.get("price_type")):
            changed.append({
                "name": n["name"],
                "old_low": o.get("amount_low"), "old_high": o.get("amount_high"),
                "new_low": n.get("amount_low"), "new_high": n.get("amount_high"),
                "old_price_type": o.get("price_type"), "new_price_type": n.get("price_type"),
            })
        if not has_known_price(o) and has_known_price(n):
            resolved.append(n["name"])
    added = [{"name": n["name"], "item_id": n["item_id"], "price_type": n.get("price_type"),
              "amount_low": n.get("amount_low"), "amount_high": n.get("amount_high")}
             for n in new_items if id(n) not in m_new]
    removed = [{"name": o["name"], "item_id": o["item_id"], "price_type": o.get("price_type"),
                "amount_low": o.get("amount_low"), "amount_high": o.get("amount_high")}
               for o in old_items if id(o) not in m_old]

    # Unresolved entries ("A: crematory fee") that no longer appear after replanning.
    def _strip(u: str) -> str:
        return u.split(":", 1)[1].strip() if ":" in u else u.strip()
    new_unres = {_strip(u).lower() for u in new_plan["unresolved"]}
    for u in old_plan["unresolved"]:
        name = _strip(u)
        if name.lower() not in new_unres and not any(name_similarity(name, r) >= 0.5 for r in resolved):
            resolved.append(name)

    diff = {
        "changed": changed,
        "added": added,
        "removed": removed,
        "resolved_unknowns": resolved,
        "old_totals": _totals(old_plan),
        "new_totals": _totals(new_plan),
    }
    return new_plan, diff
