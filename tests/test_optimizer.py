"""Optimizer + replan tests on inline fixtures mirroring spec §4 (providers fictional)."""
from __future__ import annotations

from pipeline.optimizer import (
    best_plan,
    budget_status,
    match_items,
    merge_quote,
    plan_for_quote,
    plan_notes,
    replan,
)
from pipeline.wishes import parse_wishes

LINDA = "Keep it simple. Cremation, no public viewing. Please avoid unnecessary extras."
DAUGHTER = "I confirm Mom's wishes. Our working budget is about $4,000."


def wishes():
    return parse_wishes(LINDA, "wish-linda-note") + parse_wishes(DAUGHTER, "wish-daughter-confirm")


def li(item_id, name, category, price_type, lo, hi, excerpt, provider=None, quote_id=None):
    provider = provider or item_id.split("-")[0]
    return {
        "item_id": item_id, "quote_id": quote_id or f"{provider}-v1", "provider": provider,
        "name": name, "category": category, "price_type": price_type,
        "amount_low": lo, "amount_high": hi, "excerpt": excerpt,
        "source_doc": f"quote_{provider}.txt", "confidence": 0.9,
    }


def quote_a():
    return [
        li("A-01", "Basic services of staff", "basic_fee", "fixed", 495.0, 495.0,
           "Basic services of staff ... $495"),
        li("A-02", "Direct cremation", "basic_fee", "fixed", 400.0, 400.0,
           "Simple direct cremation, just $400 (crematory fee not included)"),
        li("A-03", "Death certificates", "cash_advance", "estimated", 30.0, 60.0,
           "Death certificates, est. $30-$60"),
    ]


def quote_b():
    return [
        li("B-01", "Basic services of funeral director and staff", "basic_fee", "fixed", 995.0, 995.0,
           "Basic services of funeral director and staff: $995"),
        li("B-02", "Direct cremation", "basic_fee", "fixed", 650.0, 650.0,
           "Direct cremation with alternative container: $650"),
        li("B-03", "Crematory fee", "basic_fee", "fixed", 395.0, 395.0, "Crematory fee: $395"),
        li("B-04", "Certified death certificates", "cash_advance", "estimated", 50.0, 100.0,
           "Certified death certificates (cash advance, estimated) $50-$100"),
        li("B-05", "Keepsake urn", "optional", "starting_at", 150.0, None, "Urns from $150"),
    ]


def quote_c():
    return [
        li("C-01", "Basic services", "basic_fee", "fixed", 1295.0, 1295.0, "Basic services $1,295"),
        li("C-02", "Direct cremation", "basic_fee", "fixed", 795.0, 795.0,
           "Direct cremation, crematory fee included, $795"),
        li("C-03", "Public viewing and visitation", "package", "fixed", 650.0, 650.0,
           "Memorial package includes public viewing and visitation ($650)"),
        li("C-04", "Embalming", "package", "fixed", 795.0, 795.0, "Embalming ... $795"),
        li("C-05", "Floral arrangement", "optional", "fixed", 350.0, 350.0, "Floral arrangement $350"),
        li("C-06", "Casket", "stated_requirement", "fixed", 1495.0, 1495.0,
           "A casket purchase is required for direct cremation."),
    ]


def quotes():
    return {"A-v1": quote_a(), "B-v1": quote_b(), "C-v1": quote_c()}


# ---- wishes ----------------------------------------------------------------

def test_parse_wishes_ids_and_budget():
    ws = wishes()
    assert [w["wish_id"] for w in ws] == ["W1", "W2", "W3", "W4"]
    assert ws[3]["value"] == 4000.0
    assert ws[0]["source_id"] == "wish-linda-note"


# ---- best_plan -------------------------------------------------------------

def test_plan_shape_matches_contract():
    p = plan_for_quote("B-v1", quote_b(), wishes())
    assert set(p) == {"plan_id", "quote_id", "items", "known_total", "estimated_low", "estimated_high",
                      "unresolved", "not_needed", "wishes_satisfied", "notes"}


def test_a_unresolved_never_zero_and_never_chosen():
    chosen, plans = best_plan(quotes(), wishes())
    a = next(p for p in plans if p["quote_id"] == "A-v1")
    assert a["unresolved"] == ["A: crematory fee"]
    assert a["known_total"] == 895.0           # crematory fee not counted as $0 in a "total"
    assert budget_status(a, wishes()) == "unknown"
    assert "W4" not in a["wishes_satisfied"]
    # A is the lowest headline but must not be chosen
    assert a["known_total"] < chosen["known_total"]
    assert chosen["quote_id"] != "A-v1"
    assert [p["quote_id"] for p in plans][0] == "B-v1"   # resolved plans rank first
    assert {p["quote_id"] for p in plans[1:]} == {"A-v1", "C-v1"}


def test_b_baseline_chosen():
    chosen, _ = best_plan(quotes(), wishes())
    assert chosen["quote_id"] == "B-v1"
    assert chosen["items"] == ["B-01", "B-02", "B-03", "B-04"]
    assert chosen["known_total"] == 2040.0
    assert chosen["estimated_low"] == 50.0 and chosen["estimated_high"] == 100.0
    assert chosen["unresolved"] == []
    assert chosen["wishes_satisfied"] == ["W1", "W2", "W3", "W4"]
    assert chosen["not_needed"] == [{"item_id": "B-05", "savings": 150.0}]
    assert budget_status(chosen, wishes()) == "within"


def test_c_not_needed_with_savings_and_casket_kept():
    p = plan_for_quote("C-v1", quote_c(), wishes())
    nn = {n["item_id"]: n["savings"] for n in p["not_needed"]}
    assert nn == {"C-03": 650.0, "C-04": 795.0, "C-05": 350.0}
    # stated requirement is flagged elsewhere, never auto-removed
    assert "C-06" in p["items"]
    assert p["known_total"] == 1295.0 + 795.0 + 1495.0
    assert "W3" not in p["wishes_satisfied"]
    assert any("under review" in n for n in plan_notes(p, quote_c(), wishes()))
    assert p["notes"] == plan_notes(p, quote_c(), wishes())
    assert p["unresolved"] == ["C: alternative container (price not quoted)"]


def test_open_ended_starting_at_gives_none_high():
    items = [li("D-01", "Direct cremation", "basic_fee", "starting_at", 900.0, None,
                "Direct cremation (crematory fee included) starting at $900")]
    p = plan_for_quote("D-v1", items, wishes())
    assert p["estimated_low"] == 900.0 and p["estimated_high"] is None
    assert budget_status(p, wishes()) == "unknown"


def test_unremovable_package_item_kept_and_noted():
    items = quote_b()[:3] + [li("E-09", "Viewing", "package", "unknown", None, None,
                                "Package includes a viewing")]
    p = plan_for_quote("E-v1", items, wishes())
    assert "E-09" in p["items"]
    assert "W2" not in p["wishes_satisfied"]
    assert "B: Viewing" in p["unresolved"]
    assert any("cannot be removed" in n for n in plan_notes(p, items, wishes()))


# ---- replan ----------------------------------------------------------------

def test_replan_after_a_supplies_crematory_fee():
    ws = wishes()
    old_plan = plan_for_quote("A-v1", quote_a(), ws)
    reply = [li("R-01", "Crematorium charge", "basic_fee", "fixed", 395.0, 395.0,
                "Our crematorium charge is $395.", provider="A", quote_id="A-v2")]
    v1 = quote_a()
    v2 = merge_quote(v1, reply, "A-v2")
    assert [i["quote_id"] for i in v1] == ["A-v1"] * 3          # v1 kept unchanged
    assert {i["quote_id"] for i in v2} == {"A-v2"}

    new_plan, diff = replan(old_plan, v1, v2, ws)
    assert new_plan["quote_id"] == "A-v2"
    assert new_plan["unresolved"] == []
    assert new_plan["known_total"] == 895.0 + 395.0
    assert "crematory fee" in diff["resolved_unknowns"]
    assert [a["name"] for a in diff["added"]] == ["Crematorium charge"]
    assert diff["removed"] == [] and diff["changed"] == []
    assert diff["old_totals"]["unresolved"] == ["A: crematory fee"]
    assert diff["new_totals"]["known_total"] == 1290.0

    # recomputed comparison: A v2 is now complete and cheapest
    chosen, _ = best_plan({"A-v2": v2, "B-v1": quote_b(), "C-v1": quote_c()}, ws)
    assert chosen["quote_id"] == "A-v2"


def test_replan_changed_and_unknown_item_resolved():
    ws = wishes()
    v1 = quote_a() + [li("A-04", "Crematory fee", "basic_fee", "unknown", None, None,
                         "Crematory fee: call for pricing")]
    old_plan = plan_for_quote("A-v1", v1, ws)
    assert "A: Crematory fee" in old_plan["unresolved"]
    v2 = merge_quote(v1, [li("X-1", "crematory fees", "basic_fee", "fixed", 395.0, 395.0,
                             "Crematory fees are $395", provider="A", quote_id="A-v2"),
                          li("X-2", "Direct Cremation", "basic_fee", "fixed", 425.0, 425.0,
                             "Direct cremation is now $425", provider="A", quote_id="A-v2")], "A-v2")
    new_plan, diff = replan(old_plan, v1, v2, ws)
    names = {c["name"]: c for c in diff["changed"]}
    assert names["crematory fees"]["old_price_type"] == "unknown"
    assert names["crematory fees"]["new_low"] == 395.0
    assert names["Direct Cremation"]["old_low"] == 400.0 and names["Direct Cremation"]["new_low"] == 425.0
    assert "crematory fees" in diff["resolved_unknowns"]
    assert diff["added"] == [] and diff["removed"] == []
    assert new_plan["unresolved"] == []


def test_match_items_by_name_not_id():
    pairs = match_items(quote_b(), [li("Z-77", "Basic Services of the Funeral Director & Staff", "basic_fee",
                                      "fixed", 995.0, 995.0, "x")])
    assert len(pairs) == 1 and pairs[0][0]["item_id"] == "B-01"


# ---- fixtures mirroring data/ seed files (issues found on real seed data) ---

WISHES_FILE = """FICTIONAL PERSON \u2014 for demo. Linda is not a real person.
# Wish IDs derived from this note: W1 cremation \u00b7 W2 no public viewing \u00b7 W3 avoid unnecessary extras
# (W4 budget comes from confirmation_daughter.txt)

SOURCE: W-NOTE-1
TYPE: Recorded note (voice memo, transcribed)
SPEAKER: Linda Marsh, age 78

"Keep it simple. Cremation, no public viewing. Please avoid unnecessary extras."
"""

CONFIRM_FILE = """FICTIONAL PERSON \u2014 for demo. Maya is not a real person.
# Confirms W1, W2, W3 from W-NOTE-1 and adds W4 (working budget about $4,000).

SOURCE: W-CONF-1
FROM: Maya Marsh, daughter
REFERS TO: W-NOTE-1

I have listened to Mom's recorded note and I confirm these are her wishes:

- She wanted cremation.
- She did not want a public viewing.

Our family's working budget for the arrangements is about $4,000. We would
like to choose only the services that match what Mom asked for.

\u2014 Maya Marsh
"""


def seed_wishes():
    from pipeline.wishes import merge_wishes
    return merge_wishes(parse_wishes(WISHES_FILE), parse_wishes(CONFIRM_FILE))


def quote_a_seed():
    return [
        li("A-01", "Basic services of funeral director and staff", "basic_fee", "fixed", 895.0, 895.0,
           "| Basic services of funeral director and staff | $895.00 | Non-declinable |"),
        li("A-02", "Alternative container (fiberboard)", "optional", "fixed", 75.0, 75.0,
           "| Alternative container (fiberboard) | $75.00 |"),
        li("A-03", "Crematory charges", "basic_fee", "unknown", None, None,
           "| Crematory charges | TBC | To be confirmed |"),
    ]


def quote_c_seed():
    return [
        li("C-01", "Basic services of funeral director and staff", "basic_fee", "fixed", 1350.0, 1350.0,
           "Basic services of funeral director and staff \u2014 $1,350.00"),
        li("C-02", "Embalming", "package", "fixed", 795.0, 795.0, "Embalming \u2014 $795"),
        li("C-03", "Cremation casket, oak finish", "optional", "fixed", 1895.0, 1895.0,
           "Cremation casket, oak finish \u2014 $1,895.00"),
        li("C-04", "Crematory fee", "basic_fee", "fixed", 375.0, 375.0, "Crematory fee \u2014 $375"),
        li("C-05", "Casket requirement", "stated_requirement", "unknown", None, None,
           "A casket purchase is required for direct cremation."),
        li("C-06", "Upgraded urn", "optional", "unknown", None, None,
           "Upgraded urns are available from our selection room."),
    ]


def test_issue1_one_unresolved_entry_for_listed_unpriced_crematory():
    p = plan_for_quote("A-v1", quote_a_seed(), seed_wishes())
    assert p["unresolved"] == ["A: Crematory charges"]


def test_issue2_wish_text_ignores_headers():
    ws = seed_wishes()
    assert [w["wish_id"] for w in ws] == ["W1", "W2", "W3", "W4"]
    for w in ws:
        assert not w["text"].startswith("#")
        assert "FICTIONAL" not in w["text"] and "SOURCE" not in w["text"] and "Wish IDs" not in w["text"]
    assert ws[0]["text"] == "Cremation, no public viewing." and ws[0]["source_id"] == "W-NOTE-1"
    assert ws[2]["text"] == "Please avoid unnecessary extras."
    assert ws[3]["source_id"] == "W-CONF-1" and ws[3]["value"] == 4000.0
    assert ws[3]["text"] == "Our family's working budget for the arrangements is about $4,000."


def test_issue3_casket_kept_under_stated_requirement():
    p = plan_for_quote("C-v1", quote_c_seed(), seed_wishes())
    assert "C-03" in p["items"]
    assert "C-03" not in {n["item_id"] for n in p["not_needed"]}
    assert "C: alternative container (price not quoted)" in p["unresolved"]
    assert p["known_total"] == 1350.0 + 1895.0 + 375.0
    assert any("Cremation casket, oak finish" in n for n in p["notes"])


def test_issue4_statement_is_not_an_unresolved_charge():
    p = plan_for_quote("C-v1", quote_c_seed(), seed_wishes())
    assert p["unresolved"] == ["C: alternative container (price not quoted)"]
    assert not any("Casket requirement" in u for u in p["unresolved"])


def test_unknown_price_exclusion_listed_with_none_savings():
    p = plan_for_quote("C-v1", quote_c_seed(), seed_wishes())
    nn = {n["item_id"]: n["savings"] for n in p["not_needed"]}
    assert nn == {"C-02": 795.0, "C-06": None}


def test_priced_alt_container_resolves_casket_requirement_entry():
    items = quote_c_seed() + [li("C-07", "Alternative container (cardboard)", "optional", "fixed",
                                 95.0, 95.0, "Alternative container $95")]
    p = plan_for_quote("C-v2", items, seed_wishes())
    assert p["unresolved"] == []
