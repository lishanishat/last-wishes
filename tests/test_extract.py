"""Offline tests for pipeline.extract / pipeline.classify (no network, no SIE key needed)."""
from __future__ import annotations

import pytest

from pipeline.classify import CRITERIA, apply_categories, item_text
from pipeline.extract import (
    build_items,
    excerpt_in_text,
    find_money,
    parse_price,
    provider_of,
    segment,
)
from contracts import CATEGORIES


# --------------------------------------------------------------------------- money / price type

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Direct cremation — $1,195", ("fixed", 1195.0, 1195.0)),
        ("Direct cremation 1195.00", ("fixed", 1195.0, 1195.0)),
        ("Transfer of remains — 1,195 USD", ("fixed", 1195.0, 1195.0)),
        ("Transfer: 425 dollars", ("fixed", 425.0, 425.0)),
        ("Basic services are $1,495.00.", ("fixed", 1495.0, 1495.0)),
        ("death certificate copies, estimated $24–$48", ("estimated", 24.0, 48.0)),
        ("copies $24-48", ("estimated", 24.0, 48.0)),
        ("copies between $24 to $48", ("estimated", 24.0, 48.0)),
        ("Floral arrangement — starting at $350", ("starting_at", 350.0, None)),
        ("Urns from $125", ("starting_at", 125.0, None)),
        ("Certified copies | est. $96 | Cash advance", ("estimated", 96.0, 96.0)),
        ("about $200 for permits", ("estimated", 200.0, 200.0)),
        ("$24 per copy, est. $48–$96", ("estimated", 48.0, 96.0)),
        ("Crematory charges | TBC | To be confirmed", ("unknown", None, None)),
        ("Crematory fee: to be determined", ("unknown", None, None)),
        ("A casket purchase is required for direct cremation.", ("unknown", None, None)),
        ("returned in a temporary container at no additional charge", ("fixed", 0.0, 0.0)),
        # corrections: the superseded amount is ignored
        ("our refrigeration charge was listed at $150, but for 7 days it is $195.", ("fixed", 195.0, 195.0)),
        ("revised to 195 USD (previously stated as $150)", ("fixed", 195.0, 195.0)),
        ("three hundred ninety-five dollars ($395.00)", ("fixed", 395.0, 395.0)),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_unknown_is_never_zero():
    for t in ["Crematory charges | TBC", "Crematory fee: pending", "Crematory fee"]:
        ptype, lo, hi = parse_price(t)
        assert ptype == "unknown" and lo is None and hi is None


def test_non_money_numbers_ignored():
    assert find_money("Within 25 miles, up to 7 days, set of 100, 4 copies, November 18, 2026") == []


# --------------------------------------------------------------------------- excerpts / segments

def test_excerpt_validation():
    text = "The crematory fee is\n$350.00. Thanks."
    assert excerpt_in_text("The crematory fee is\n$350.00.", text)
    assert excerpt_in_text("The crematory fee is $350.00.", text)  # rewrapped whitespace ok
    assert not excerpt_in_text("The crematory fee is $395.00.", text)
    assert not excerpt_in_text("", text)


def test_segments_are_verbatim_offsets():
    text = (
        "| Item | Price |\n|---|---|\n| Transfer of remains | $350.00 |\n\n"
        "  • Embalming — $795\n\nOur basic fee is $1,495.00. The crematory fee\nis $350.00.\n"
    )
    for s in segment(text):
        assert text[s.start : s.end] == s.text
    kinds = [s.kind for s in segment(text)]
    assert kinds == ["table", "bullet", "prose", "prose"]  # header + separator rows skipped


def test_provider_and_item_ids():
    assert provider_of("A-v2") == "A"
    assert provider_of("B-v1") == "B"
    items = build_items("• Embalming — $795\n• Crematory fee — TBC\n", "q.txt", "C-v1")
    assert [i["item_id"] for i in items] == ["C-01", "C-02"]
    assert all(i["provider"] == "C" and i["quote_id"] == "C-v1" for i in items)


# --------------------------------------------------------------------------- build_items (offline)

QUOTE = """ACME FUNERAL (fictional)

| Item                         | Price    | Notes         |
|------------------------------|----------|---------------|
| Basic services of staff      | $895.00  | Non-declinable|
| Crematory charges            | TBC      | To be confirmed |

  • Floral arrangement — starting at $350
  • Certified copies of death certificate — $24 per copy, est. $48–$96

Quoted total: $895.00
A casket purchase is required for direct cremation.
"""


def test_build_items_offline():
    items = build_items(QUOTE, "quote_X.txt", "X-v1")
    by_name = {i["name"]: i for i in items}
    assert "Quoted total" not in " ".join(by_name)  # totals skipped
    assert by_name["Basic services of staff"]["amount_low"] == 895.0
    crem = by_name["Crematory charges"]
    assert crem["price_type"] == "unknown" and crem["amount_low"] is None and crem["amount_high"] is None
    flor = by_name["Floral arrangement"]
    assert (flor["price_type"], flor["amount_low"], flor["amount_high"]) == ("starting_at", 350.0, None)
    dc = by_name["Certified copies of death certificate"]
    assert (dc["price_type"], dc["amount_low"], dc["amount_high"]) == ("estimated", 48.0, 96.0)
    req = [i for i in items if "required" in i["excerpt"]]
    assert len(req) == 1 and req[0]["price_type"] == "unknown"
    for i in items:
        assert i["excerpt"] in QUOTE
        assert 0.0 <= i["confidence"] <= 1.0


def test_sie_spans_name_prose_and_bad_spans_ignored():
    text = "Thank you.\n\nOur crematory fee is $395, and it would be added.\n"
    segs = segment(text)
    ents = []
    for s in segs:
        if "crematory" in s.text:
            ents.append([
                {"text": "crematory fee", "label": "fee or charge", "score": 0.91, "start": 4, "end": 17},
                {"text": "hallucinated item", "label": "funeral service", "score": 0.99},
            ])
        else:
            ents.append([])
    items = build_items(text, "reply.txt", "A-v2", ents, segs)
    assert len(items) == 1
    assert items[0]["name"] == "crematory fee"
    assert items[0]["confidence"] == 0.91
    assert items[0]["amount_low"] == 395.0


def test_reply_with_correction_offline():
    text = (
        "Our crematory fee is $395.\n\n"
        "One other correction: our refrigeration charge was listed at $150, but for\n"
        "an arrangement of up to 7 days it is $195.\n\n"
        "With these changes, the known charges come to $1,910.00.\n"
    )
    items = build_items(text, "reply.txt", "A-v2")
    amounts = sorted(i["amount_low"] for i in items)
    assert amounts == [195.0, 395.0]  # total skipped, old $150 ignored


# --------------------------------------------------------------------------- classify (offline part)

def test_criteria_cover_contract_categories():
    assert tuple(CRITERIA) == CATEGORIES


def test_apply_categories_picks_top_label():
    items = build_items("A casket purchase is required for direct cremation.\n• Embalming — $795\n", "c.txt", "C-v1")
    probs = [
        {"stated_requirement": 0.8, "optional": 0.1},
        {"optional": 0.7, "basic_fee": 0.2},
    ]
    out = apply_categories(items, probs)
    assert [i["category"] for i in out] == ["stated_requirement", "optional"]
    assert items[0]["category"] == "basic_fee"  # input not mutated
    assert "required" in item_text(out[0])


def test_missing_key_raises(monkeypatch):
    from pipeline import sie_client

    monkeypatch.setattr(sie_client, "_client", None)
    monkeypatch.setattr(sie_client, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("SIE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SIE_API_KEY not set"):
        sie_client.extract(["x"], ["price"])


def test_sie_client_with_fake_sdk(monkeypatch):
    """Wire shapes from the docs/SDK: extract -> entities, Decide -> data.category.probabilities,
    score -> scores[{item_id, score}]. Checks the wrapper parses them and returns traces."""
    from pipeline import sie_client

    class Fake:
        def extract(self, model, items, **kw):
            if "output_schema" in kw:
                return [{"data": {"category": {"probabilities": {"optional": 0.7, "package": 0.3}}}} for _ in items]
            return [{"entities": [{"text": "fee", "label": "fee or charge", "score": 0.9, "start": 0, "end": 3}]}
                    for _ in items]

        def score(self, model, query, items, **kw):
            return {"scores": [{"item_id": "1", "score": 0.9, "rank": 0}, {"item_id": "0", "score": 0.1, "rank": 1}]}

    monkeypatch.setattr(sie_client, "_client", Fake())
    ents, tr = sie_client.extract(["fee $5", "x"], ["fee or charge"])
    assert ents[0][0]["text"] == "fee" and len(tr) == 1
    assert set(tr[0]) == {"recipe", "model", "latency_ms", "input_chars"} and tr[0]["input_chars"] == 7
    probs, tr = sie_client.classify(["a"], {"optional": "x", "package": "y"}, question="q")
    assert probs == [{"optional": 0.7, "package": 0.3}] and tr[0]["recipe"] == "classify"
    ranked, tr = sie_client.rerank("q", ["a", "b"])
    assert ranked[0] == (1, 0.9) and tr["recipe"] == "rerank"
