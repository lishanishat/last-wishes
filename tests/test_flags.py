"""Review-flag tests on inline fixtures mirroring spec §4 (providers fictional)."""
from __future__ import annotations

from pipeline.flags import STATED_REQUIREMENT_MESSAGE, load_ftc_refs, parse_ftc_refs, review_flags
from tests.test_optimizer import li, quote_a, quote_b, quote_c, wishes

FTC_RAW = """\
ID: FTC-ALT-CONTAINER
URL: https://consumer.ftc.gov/articles/ftc-funeral-rule
TEXT: Funeral providers who offer cremations must make alternative containers
  available.
---
id: FTC-ITEMIZED
text: You have the right to get an itemized statement of the goods and services you choose.
url: https://consumer.ftc.gov/articles/ftc-funeral-rule
---

---
TEXT: You can choose only the goods and services you want. Source https://consumer.ftc.gov/x
"""


def refs():
    return parse_ftc_refs(FTC_RAW)


def all_items():
    return quote_a() + quote_b() + quote_c()


def test_parse_ftc_refs_tolerant(tmp_path):
    r = refs()
    assert [x["id"] for x in r] == ["FTC-ALT-CONTAINER", "FTC-ITEMIZED", "FTC-3"]
    assert r[0]["text"].endswith("make alternative containers available.")
    assert r[2]["url"] == "https://consumer.ftc.gov/x"
    p = tmp_path / "ftc_reference.txt"
    p.write_text(FTC_RAW)
    assert load_ftc_refs(p) == r


def test_a_missing_crematory_fee_unresolved():
    flags = [f for f in review_flags(all_items(), wishes(), refs()) if f["quote_id"] == "A-v1"]
    assert len(flags) == 1
    f = flags[0]
    assert f["kind"] == "unresolved_charge" and f["flag_id"] == "A-F1" and f["item_id"] is None
    assert f["message"] == "Needs clarification: crematory fee has no stated price."
    assert "crematory fee not included" in f["excerpt"]
    assert "itemized" in f["reference"]


def test_listed_but_unpriced_crematory_fee():
    items = quote_a() + [li("A-04", "Crematory fee", "basic_fee", "unknown", None, None,
                            "Crematory fee: call")]
    flags = review_flags(items, wishes(), refs())
    assert [(f["kind"], f["item_id"], f["message"]) for f in flags] == [
        ("unresolved_charge", "A-04", "Needs clarification: Crematory fee has no stated price.")]


def test_b_has_no_flags():
    assert review_flags(quote_b(), wishes(), refs()) == []


def test_c_not_selected_and_casket_flag():
    flags = review_flags(quote_c(), wishes(), refs())
    ns = [f for f in flags if f["kind"] == "not_selected"]
    assert {f["item_id"] for f in ns} == {"C-03", "C-04", "C-05"}
    msg = {f["item_id"]: f["message"] for f in ns}
    assert "$650" in msg["C-03"] and "W2" in msg["C-03"]
    assert "$795" in msg["C-04"] and "$350" in msg["C-05"]

    sr = [f for f in flags if f["kind"] == "stated_requirement"]
    assert len(sr) == 1
    f = sr[0]
    assert f["item_id"] == "C-06"
    assert f["excerpt"] == "A casket purchase is required for direct cremation."
    assert f["message"] == ("FTC guidance requires an alternative-container option for direct cremation. "
                            "Ask the provider to clarify this requirement and quote that option.")
    assert f["message"] == STATED_REQUIREMENT_MESSAGE
    assert "alternative containers" in f["reference"]
    assert "https://consumer.ftc.gov" in f["reference"]
    assert [x["flag_id"] for x in flags] == [f"C-F{i}" for i in range(1, len(flags) + 1)]


def test_casket_requires_category_and_text():
    # same words but classified optional -> no stated_requirement flag
    item = li("C-06", "Casket", "optional", "fixed", 1495.0, 1495.0,
              "A casket purchase is required for direct cremation.")
    assert not [f for f in review_flags([item], wishes(), refs()) if f["kind"] == "stated_requirement"]


def test_no_legal_verdict_words():
    for f in review_flags(all_items(), wishes(), refs()):
        text = (f["message"] + f["reference"]).lower()
        assert "illegal" not in text and "violation" not in text


def test_flag_shape():
    for f in review_flags(all_items(), wishes(), refs()):
        assert set(f) == {"flag_id", "quote_id", "item_id", "kind", "excerpt", "reference", "message"}
