"""SIE classify of LineItems into contracts.CATEGORIES (LAST_WISHES.md §8 step 3).

Uses ``pipeline.sie_client.classify`` (fastino/GLiNER2.5-Decide, single-choice question).
An explicit optional-service rule corrects Decide's observed false ``basic_fee`` labels
for viewing, embalming and other declinable extras. A casket requirement flag still
requires SIE's ``stated_requirement`` label plus the rule in flags.py.
"""
from __future__ import annotations

import re

from contracts import CATEGORIES, LineItem, SIETrace

QUESTION = "What kind of line or statement is this in a funeral home price quote?"

# Short one-line criteria (Decide reads ~512 tokens incl. the question and options).
CRITERIA: dict[str, str] = {
    "basic_fee": "a core charge needed for the arrangement: basic services of funeral director and staff, "
    "transfer of remains, refrigeration, crematory fee, cremation or alternative container",
    "optional": "an optional extra the family may decline: embalming, viewing or visitation, ceremony, "
    "flowers, casket, urn, memorial printing, use of facilities",
    "cash_advance": "a third-party fee paid on the family's behalf and passed through at cost: "
    "death certificate copies, permits, medical examiner or county fees",
    "package": "a bundled package price covering several services together",
    "stated_requirement": "a statement by the provider that something is required or must be purchased",
}
assert tuple(CRITERIA) == CATEGORIES

_DECLINABLE_EXTRA = re.compile(
    r"\b(?:embalm\w*|viewing|visitation|memorial|flower\w*|floral|"
    r"casket|cosmetology|dressing|printed folders?|ceremony)\b", re.I
)


def item_text(item: LineItem) -> str:
    """What the classifier reads: the verbatim excerpt (name prepended if not already in it)."""
    excerpt = item["excerpt"].strip()
    name = item["name"].strip()
    return excerpt if name.lower() in excerpt.lower() else f"{name}: {excerpt}"


def apply_categories(items: list[LineItem], probs: list[dict[str, float]]) -> list[LineItem]:
    """Set each item's category to the top-probability label (offline-testable)."""
    out: list[LineItem] = []
    for item, p in zip(items, probs):
        new = LineItem(**item)  # type: ignore[typeddict-item]
        if p:
            new["category"] = max(p.items(), key=lambda kv: kv[1])[0]  # type: ignore[typeddict-item]
        if new["category"] == "basic_fee" and _DECLINABLE_EXTRA.search(new["name"]):
            new["category"] = "optional"
        out.append(new)
    return out


def classify(items: list[LineItem]) -> tuple[list[LineItem], list[SIETrace]]:
    """Return (copies of items with ``category`` set by SIE classify, traces)."""
    if not items:
        return [], []
    from pipeline import sie_client

    probs, traces = sie_client.classify(
        [item_text(i) for i in items], CRITERIA, question=QUESTION
    )
    return apply_categories(items, probs), traces
