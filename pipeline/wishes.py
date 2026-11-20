"""Wish model and generic wish-vs-item rules (LAST_WISHES.md §4, §8 steps 6 and 8).

Pure Python. Matching is by generic keywords and categories, never by provider.

Wish kinds and their fixed IDs:
    W1 cremation     - plan must include a cremation service
    W2 no_viewing    - exclude viewing / visitation items
    W3 avoid_extras  - exclude optional / package extras (flowers, embalming, casket...)
    W4 budget        - known_total + estimated_high <= budget; "unknown" if anything unresolved
"""
from __future__ import annotations

import re
from typing import Iterable, Literal, Optional, TypedDict

from contracts import LineItem

WishKind = Literal["cremation", "no_viewing", "avoid_extras", "budget", "other"]

WISH_IDS: dict[str, str] = {
    "cremation": "W1",
    "no_viewing": "W2",
    "avoid_extras": "W3",
    "budget": "W4",
}


class Wish(TypedDict):
    wish_id: str
    text: str
    source_id: str
    kind: WishKind
    value: Optional[float]  # budget amount for kind == "budget", else None


# ---- keyword rules ---------------------------------------------------------

RE_CREMATION = re.compile(r"\bcremat\w*", re.I)
RE_CREMATORY_FEE = re.compile(r"\bcremator(?:y|ium|ies)\b|\bcremation (?:fee|charge|process)\b", re.I)
RE_VIEWING = re.compile(r"\bviewing\b|\bvisitation\b|\bwake\b|\blying in state\b", re.I)
RE_EMBALMING = re.compile(r"\bembalm\w*", re.I)
RE_FLOWERS = re.compile(r"\bflowers?\b|\bfloral\b|\bwreaths?\b|\bspray\b", re.I)
RE_CASKET = re.compile(r"\bcaskets?\b|\bcoffins?\b", re.I)
RE_ALT_CONTAINER = re.compile(r"alternative container|cremation container|cardboard|fiberboard", re.I)
RE_NEGATED = re.compile(
    r"not included|not incl|excluded|excludes|not part of|billed separately|separate(?:ly)?|"
    r"additional|extra charge|quoted separately|not listed",
    re.I,
)

EXTRA_PATTERNS: dict[str, re.Pattern[str]] = {
    "embalming": RE_EMBALMING,
    "flowers": RE_FLOWERS,
    "casket": RE_CASKET,
}


def item_text(item: LineItem) -> str:
    return f"{item.get('name') or ''} {item.get('excerpt') or ''}"


def is_viewing(item: LineItem) -> bool:
    return bool(RE_VIEWING.search(item.get("name") or ""))


def extra_kind(item: LineItem) -> Optional[str]:
    """Return 'embalming' / 'flowers' / 'casket' if the item's *name* is such an extra."""
    name = item.get("name") or ""
    if RE_CASKET.search(name) and RE_ALT_CONTAINER.search(name):
        return None  # an alternative container is not a casket extra
    for kind, pat in EXTRA_PATTERNS.items():
        if pat.search(name):
            return kind
    return None


def is_cremation_service(item: LineItem) -> bool:
    """Item provides cremation (direct cremation, crematory fee, ...). Caskets are never one."""
    name = item.get("name") or ""
    if RE_CASKET.search(name) and not RE_ALT_CONTAINER.search(name):
        return False
    if item.get("category") == "stated_requirement":
        return False
    return bool(RE_CREMATION.search(name) or RE_CREMATORY_FEE.search(name))


def is_crematory_fee_item(item: LineItem) -> bool:
    return bool(RE_CREMATORY_FEE.search(item.get("name") or ""))


def has_known_price(item: LineItem) -> bool:
    return item.get("price_type") != "unknown" and (
        item.get("amount_low") is not None or item.get("amount_high") is not None
    )


def covers_crematory_fee(item: LineItem) -> bool:
    """True if this priced item states that it includes the crematory charge.

    Either the item *is* the crematory fee, or its excerpt mentions the crematory
    without a negation like "not included" / "billed separately".
    """
    if not has_known_price(item):
        return False
    if is_crematory_fee_item(item):
        return True
    excerpt = item.get("excerpt") or ""
    if RE_CREMATORY_FEE.search(excerpt) and not RE_NEGATED.search(excerpt):
        return True
    return False


def offers_cremation(items: Iterable[LineItem]) -> bool:
    return any(RE_CREMATION.search(item_text(i)) for i in items)


def conflicting_wishes(item: LineItem, wishes: list[Wish]) -> list[str]:
    """Wish IDs this item conflicts with (generic keyword rules only)."""
    out: list[str] = []
    for w in wishes:
        if w["kind"] == "no_viewing" and is_viewing(item):
            out.append(w["wish_id"])
        elif w["kind"] == "avoid_extras" and extra_kind(item) is not None:
            out.append(w["wish_id"])
    return out


def wish_by_kind(wishes: list[Wish], kind: str) -> Optional[Wish]:
    for w in wishes:
        if w["kind"] == kind:
            return w
    return None


# ---- parsing ---------------------------------------------------------------

_RE_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?\s*(k)?", re.I)


def _make(kind: WishKind, text: str, source_id: str, value: Optional[float] = None) -> Wish:
    return {"wish_id": WISH_IDS[kind], "text": text, "source_id": source_id, "kind": kind, "value": value}


def parse_wishes(text: str, source_id: str) -> list[Wish]:
    """Detect the four supported wish kinds in free text (keyword rules, no LLM).

    Each wish keeps the sentence it came from as its text.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    found: dict[str, Wish] = {}
    for s in sentences:
        low = s.lower()
        if "cremation" not in found and RE_CREMATION.search(s) and not re.search(r"\bno cremation|not cremat", low):
            found["cremation"] = _make("cremation", s, source_id)
        if "no_viewing" not in found and RE_VIEWING.search(s) and re.search(r"\bno\b|\bnot\b|without|don't|do not", low):
            found["no_viewing"] = _make("no_viewing", s, source_id)
        if "avoid_extras" not in found and re.search(r"extras?\b|unnecessary|keep it simple|nothing fancy", low):
            if re.search(r"avoid|no |without|unnecessary|don't|do not", low):
                found["avoid_extras"] = _make("avoid_extras", s, source_id)
        if "budget" not in found and re.search(r"budget|spend|afford|up to|no more than", low):
            m = _RE_MONEY.search(s)
            if m:
                amt = float(m.group(1).replace(",", ""))
                if m.group(2):
                    amt *= 1000
                found["budget"] = _make("budget", s, source_id, amt)
    order = ["cremation", "no_viewing", "avoid_extras", "budget"]
    return [found[k] for k in order if k in found]


def merge_wishes(*groups: list[Wish]) -> list[Wish]:
    """Combine wishes from several sources; first occurrence of each ID wins."""
    seen: dict[str, Wish] = {}
    for g in groups:
        for w in g:
            seen.setdefault(w["wish_id"], w)
    return sorted(seen.values(), key=lambda w: w["wish_id"])
