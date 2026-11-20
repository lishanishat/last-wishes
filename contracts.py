"""Shared data contracts (LAST_WISHES.md §9). Every module imports from here.

Do not change these shapes without telling both Lisha and Manank.
"""
from __future__ import annotations

from typing import Literal, Optional, TypedDict

Category = Literal["basic_fee", "optional", "cash_advance", "package", "stated_requirement"]
PriceType = Literal["fixed", "estimated", "starting_at", "unknown"]
FlagKind = Literal["unresolved_charge", "not_selected", "stated_requirement"]

CATEGORIES: tuple[str, ...] = ("basic_fee", "optional", "cash_advance", "package", "stated_requirement")
PRICE_TYPES: tuple[str, ...] = ("fixed", "estimated", "starting_at", "unknown")
FLAG_KINDS: tuple[str, ...] = ("unresolved_charge", "not_selected", "stated_requirement")


class LineItem(TypedDict):
    """Produced by pipeline/extract.py (+ category from pipeline/classify.py)."""
    item_id: str            # e.g. "B-03"
    quote_id: str           # e.g. "B-v1"
    provider: str           # e.g. "B"
    name: str
    category: Category
    price_type: PriceType
    amount_low: Optional[float]   # None if unknown — never 0 for unknown
    amount_high: Optional[float]  # None if unknown
    excerpt: str            # verbatim span from the source document
    source_doc: str         # e.g. "quote_B.txt"
    confidence: float       # 0..1


class Flag(TypedDict):
    """Produced by pipeline/flags.py. Review flags only — never legal verdicts."""
    flag_id: str            # e.g. "C-F1"
    quote_id: str
    item_id: Optional[str]
    kind: FlagKind
    excerpt: str            # provider's own words
    reference: str          # public FTC guidance text (+ URL)
    message: str


class NotNeeded(TypedDict):
    item_id: str
    savings: float


class Plan(TypedDict):
    """Produced by pipeline/optimizer.py."""
    plan_id: str
    quote_id: str
    items: list[str]                 # item_ids
    known_total: float               # sum of fixed amounts only
    estimated_low: float             # sum of low ends of estimated/starting_at items
    estimated_high: Optional[float]  # None if open-ended (starting_at with no cap)
    unresolved: list[str]            # e.g. ["A: crematory fee"]
    not_needed: list[NotNeeded]
    wishes_satisfied: list[str]      # e.g. ["W1", "W2", "W3"]


class RecallResult(TypedDict):
    answer: str
    nodes: list[dict]
    edges: list[dict]


class SIETrace(TypedDict):
    """Metadata returned by every SIE call (logged to sie_calls)."""
    recipe: str
    model: str
    latency_ms: int
    input_chars: int


# ---- Memory API (memory/cognee_mem.py) — signatures only -------------------
# remember_wish(text: str, source_id: str) -> str            # returns node_id
# remember_quote(quote_id: str, provider: str, version: int,
#                items: list[LineItem], supersedes: str | None = None) -> None
# remember_question(question_id: str, quote_id: str, item_name: str) -> None
# remember_reply(reply_id: str, question_id: str, new_quote_id: str) -> None
# recall(query: str, *, exclude_wish_ids: list[str] | None = None) -> RecallResult
#   exclude_wish_ids implements the counterfactual mode (e.g. drop "avoid extras").
