"""Review flags (LAST_WISHES.md §4, §8 step 6). Code rules only, no LLM.

Flags are review prompts ("needs clarification"), never legal verdicts.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Optional, TypedDict

from contracts import Flag, LineItem
from pipeline.optimizer import MISSING_CREMATORY, crematory_status, held_for_requirement, item_savings
from pipeline.wishes import (
    RE_CREMATION,
    Wish,
    conflicting_wishes,
    is_casket_requirement,
    is_crematory_fee_item,
    item_text,
)

STATED_REQUIREMENT_MESSAGE = (
    "FTC guidance requires an alternative-container option for direct cremation. "
    "Ask the provider to clarify this requirement and quote that option."
)


class FtcRef(TypedDict):
    id: str
    text: str
    url: str


# ---- FTC reference loading ---------------------------------------------------

_FIELD = re.compile(r"^\s*(ID|URL|TEXT|SOURCE|TITLE|TOPIC)\s*[:=]\s*(.*)$", re.I)


def parse_ftc_refs(raw: str) -> list[FtcRef]:
    """Parse entries separated by '---' lines with ID:/URL:/TEXT: fields.

    Tolerant: field order is free, field names are case-insensitive, TEXT may span
    several lines, SOURCE is accepted for URL, missing IDs become FTC-n.
    """
    refs: list[FtcRef] = []
    blocks = re.split(r"^\s*-{3,}\s*$", raw, flags=re.M)
    for block in blocks:
        fields: dict[str, str] = {}
        current: Optional[str] = None
        loose: list[str] = []
        for line in block.splitlines():
            if line.lstrip().startswith("#"):
                continue  # comment / file header
            m = _FIELD.match(line)
            if m:
                key = m.group(1).upper()
                key = "URL" if key == "SOURCE" else key
                current = key
                fields[key] = m.group(2).strip()
            elif current == "TEXT":
                fields["TEXT"] = (fields["TEXT"] + " " + line.strip()).strip()
            elif line.strip():
                loose.append(line.strip())
        text = fields.get("TEXT") or " ".join(loose)
        if not text and not fields.get("URL"):
            continue
        url = fields.get("URL", "")
        if not url:
            m = re.search(r"https?://\S+", text)
            url = m.group(0) if m else ""
        refs.append({
            "id": fields.get("ID") or f"FTC-{len(refs) + 1}",
            "text": " ".join(text.split()),
            "url": url,
        })
    return refs


def load_ftc_refs(path: str | Path) -> list[FtcRef]:
    return parse_ftc_refs(Path(path).read_text(encoding="utf-8"))


def find_ref(ftc_refs: list[FtcRef], *patterns: str) -> Optional[FtcRef]:
    """First reference whose id or text matches any pattern (in pattern priority order)."""
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for r in ftc_refs:
            if rx.search(r.get("text", "")) or rx.search(r.get("id", "")):
                return r
    return None


def format_ref(ref: Optional[FtcRef]) -> str:
    if not ref:
        return "FTC Funeral Rule guidance (reference not loaded)"
    return f"{ref['text']} ({ref['url']})" if ref.get("url") else ref["text"]


# ---- rules -------------------------------------------------------------------

def _money(v: float) -> str:
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def _group(items: list[LineItem]) -> "OrderedDict[str, list[LineItem]]":
    g: "OrderedDict[str, list[LineItem]]" = OrderedDict()
    for it in items:
        g.setdefault(it["quote_id"], []).append(it)
    return g


def review_flags(items: list[LineItem], wishes: list[Wish], ftc_refs: list[FtcRef]) -> list[Flag]:
    """Evidence-driven review flags for one or more quotes (items may mix quotes).

    unresolved_charge  - essential cremation charge missing, or a non-optional item with no price
    not_selected       - optional/package item that conflicts with a wish
    stated_requirement - provider says a casket is required for cremation
    """
    ref_itemized = find_ref(ftc_refs, r"itemiz", r"price list", r"general price")
    ref_choose = find_ref(ftc_refs, r"buy only", r"only (?:the )?(?:goods|items|services|funeral)", r"choose", r"itemiz")
    ref_container = find_ref(ftc_refs, r"alternative container", r"unfinished wood", r"container")

    wish_text = {w["wish_id"]: w["text"] for w in wishes}
    flags: list[Flag] = []
    counters: dict[str, int] = {}

    def add(quote_id: str, provider: str, item_id: Optional[str], kind: str,
            excerpt: str, reference: str, message: str) -> None:
        counters[provider] = counters.get(provider, 0) + 1
        flags.append({
            "flag_id": f"{provider}-F{counters[provider]}",
            "quote_id": quote_id, "item_id": item_id, "kind": kind,  # type: ignore[typeddict-item]
            "excerpt": excerpt, "reference": reference, "message": message,
        })

    for quote_id, q_items in _group(items).items():
        provider = q_items[0].get("provider") or quote_id.split("-")[0]
        wants_cremation = any(w["kind"] == "cremation" for w in wishes)

        # 1. unresolved_charge
        unresolved_ids: set[str] = set()
        status = crematory_status(q_items) if wants_cremation else "n/a"
        if status in ("unpriced", "missing"):
            named = [i for i in q_items if is_crematory_fee_item(i)]
            if status == "unpriced":  # listed but unpriced: one flag per listed item
                for it in named:
                    unresolved_ids.add(it["item_id"])
                    add(quote_id, provider, it["item_id"], "unresolved_charge", it.get("excerpt", ""),
                        format_ref(ref_itemized), f"Needs clarification: {it['name']} has no stated price.")
            else:  # not listed at all: quote the provider's cremation line as evidence
                evidence = next((i for i in q_items if RE_CREMATION.search(item_text(i))), q_items[0])
                add(quote_id, provider, None, "unresolved_charge", evidence.get("excerpt", ""),
                    format_ref(ref_itemized), f"Needs clarification: {MISSING_CREMATORY} has no stated price.")
        for it in q_items:
            if it["item_id"] in unresolved_ids:
                continue
            if it.get("category") in ("basic_fee", "cash_advance") and it.get("price_type") == "unknown" \
                    and not conflicting_wishes(it, wishes):
                add(quote_id, provider, it["item_id"], "unresolved_charge", it.get("excerpt", ""),
                    format_ref(ref_itemized), f"Needs clarification: {it['name']} has no stated price.")

        # 2. not_selected
        for it in q_items:
            if it.get("category") not in ("optional", "package"):
                continue
            if held_for_requirement(it, q_items):
                continue  # casket under a stated requirement: the stated_requirement flag covers it
            conflicts = conflicting_wishes(it, wishes)
            if not conflicts:
                continue
            s = item_savings(it)
            amount = _money(s) if s is not None else "price not stated"
            why = "; ".join(f'{wid}: "{wish_text[wid]}"' for wid in conflicts)
            add(quote_id, provider, it["item_id"], "not_selected", it.get("excerpt", ""),
                format_ref(ref_choose),
                f"Not needed: {it['name']} ({amount}). Not part of the family's wishes ({why}).")

        # 3. stated_requirement (casket required for cremation)
        for it in q_items:
            if is_casket_requirement(it):
                add(quote_id, provider, it["item_id"], "stated_requirement", it.get("excerpt", ""),
                    format_ref(ref_container), STATED_REQUIREMENT_MESSAGE)

    return flags
