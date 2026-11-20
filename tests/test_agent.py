"""Offline tests for the orchestrator (agent.py) and drafting fallbacks.

Real: db (sqlite tmp), approvals, outbox, pipeline.wishes/flags/optimizer.
Faked: SIE extract/classify, Cognee memory, Persona — injected into sys.modules.
The fake extract returns fixed items per document; it exists only in tests.
"""
from __future__ import annotations

import sys
import types

import pytest

import agent
import db
import drafting

# ---------------------------------------------------------------------------
# Fixtures: fake modules
# ---------------------------------------------------------------------------


def _it(n, name, cat, pt, lo, hi, excerpt, prov="A"):
    return {"item_id": f"{prov}-{n:02d}", "quote_id": "", "provider": prov, "name": name, "category": cat,
            "price_type": pt, "amount_low": lo, "amount_high": hi, "excerpt": excerpt,
            "source_doc": "", "confidence": 0.9}


FAKE_DOCS = {
    "quote_A.txt": [
        _it(1, "Basic services of funeral director and staff", "basic_fee", "fixed", 895.0, 895.0, "Basic services $895.00"),
        _it(2, "Transfer of remains to funeral home", "basic_fee", "fixed", 350.0, 350.0, "Transfer $350.00"),
        _it(3, "Refrigeration / sheltering of remains", "optional", "fixed", 150.0, 150.0, "Refrigeration $150.00"),
        _it(4, "Alternative container (fiberboard)", "basic_fee", "fixed", 75.0, 75.0, "Alternative container $75.00"),
        _it(5, "Crematory charges", "basic_fee", "unknown", None, None, "Crematory charges | TBC"),
    ],
    "reply_A_v2.txt": [
        _it(1, "Crematory fee", "basic_fee", "fixed", 395.0, 395.0, "Our crematory fee is $395"),
        _it(2, "Refrigeration charge", "optional", "fixed", 195.0, 195.0, "up to 7 days it is $195"),
        _it(3, "Known charges total", "basic_fee", "fixed", 1910.0, 1910.0, "the known charges come to $1,910.00"),
    ],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LW_DB", "sqlite")
    monkeypatch.setenv("LW_SQLITE_PATH", str(tmp_path / "t.sqlite"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db.close_conn()
    db.init_schema()

    calls = {"remember": [], "persona_ok": False}

    extract = types.ModuleType("pipeline.extract")

    def extract_quote(text, source_doc, quote_id):
        items = []
        for raw in FAKE_DOCS[source_doc]:
            it = dict(raw)
            it["quote_id"], it["source_doc"] = quote_id, source_doc
            items.append(it)
        return items, [{"recipe": "extract", "model": "fake-gliner", "latency_ms": 12, "input_chars": len(text)}]

    extract.extract_quote = extract_quote
    classify = types.ModuleType("pipeline.classify")
    classify.classify = lambda items: (items, [{"recipe": "classify", "model": "fake", "latency_ms": 3,
                                                "input_chars": 10}])
    mem = types.ModuleType("memory.cognee_mem")
    for name in ("remember_wish", "remember_quote", "remember_question", "remember_reply"):
        mem.__dict__[name] = (lambda n: lambda *a, **k: calls["remember"].append((n, a, k)))(name)
    mem.recall = lambda query, exclude_wish_ids=None: {
        "query": query, "answer": "Crematory fee for A was pending.",
        "nodes": [{"id": "q1", "name": "Question"}], "edges": [{"source": "q1", "target": "A-v1", "relationship": "ABOUT"}]}
    mem.graph_snapshot = lambda: {"nodes": [], "edges": []}
    mem.reset_memory = lambda: None
    persona = types.ModuleType("persona")
    persona.is_approved = lambda inquiry_id: calls["persona_ok"]
    persona.PERSONA_COPY = "Persona verifies who is approving — not legal authority."

    monkeypatch.setitem(sys.modules, "pipeline.extract", extract)
    monkeypatch.setitem(sys.modules, "pipeline.classify", classify)
    monkeypatch.setitem(sys.modules, "memory.cognee_mem", mem)
    monkeypatch.setitem(sys.modules, "persona", persona)

    data = tmp_path / "data"
    data.mkdir()
    for name in FAKE_DOCS:
        (data / name).write_text(f"fake document {name}\narrangements@provider-a.example\n")
    yield {"calls": calls, "data": data}
    db.close_conn()


# ---------------------------------------------------------------------------
# Pure merge logic
# ---------------------------------------------------------------------------


def _v1():
    items = [dict(i, quote_id="A-v1") for i in FAKE_DOCS["quote_A.txt"]]
    return items


def test_merge_resolves_unknown_updates_changed_keeps_rest():
    reply = [dict(i, quote_id="A-v2") for i in FAKE_DOCS["reply_A_v2.txt"]]
    v2, changes = agent.merge_reply(_v1(), reply, "A-v2", "A")
    by_name = {i["name"]: i for i in v2}
    crem = by_name["Crematory charges"]
    assert crem["price_type"] == "fixed" and crem["amount_low"] == 395.0
    assert crem["category"] == "basic_fee"  # v1 category kept
    assert by_name["Refrigeration / sheltering of remains"]["amount_low"] == 195.0
    assert by_name["Basic services of funeral director and staff"]["amount_low"] == 895.0
    assert len(v2) == 5  # total line skipped, nothing added
    assert all(i["quote_id"] == "A-v2" for i in v2)
    assert {c["kind"] for c in changes} == {"resolved", "changed"}
    assert crem["item_id"] == "A-05.v2"


def test_merge_does_not_mutate_v1_and_adds_unmatched():
    v1 = _v1()
    reply = [_it(9, "Urn (keepsake)", "optional", "fixed", 60.0, 60.0, "Keepsake urn $60")]
    v2, changes = agent.merge_reply(v1, reply, "A-v2", "A")
    assert v1[4]["amount_low"] is None and v1[0]["quote_id"] == "A-v1"
    assert len(v2) == 6 and changes[0]["kind"] == "added"
    assert v2[-1]["item_id"] == "A-R01"


def test_merge_prefers_unresolved_item_and_ignores_weak_overlap():
    v1 = [_it(1, "Direct cremation (basic)", "basic_fee", "fixed", 1195.0, 1195.0, "x"),
          _it(2, "Crematory fee", "basic_fee", "unknown", None, None, "TBC")]
    reply = [_it(1, "Crematory fee", "basic_fee", "fixed", 395.0, 395.0, "fee is $395")]
    v2, _ = agent.merge_reply(v1, reply, "A-v2", "A")
    assert v2[0]["amount_low"] == 1195.0
    assert v2[1]["amount_low"] == 395.0


def test_merge_matches_service_named_in_reply_excerpt():
    old = [_it(1, "Certified copies of death certificate", "cash_advance", "estimated", 96.0, 96.0,
               "Certified copies of death certificate — est. $96")]
    reply = [_it(1, "county's cost", "cash_advance", "estimated", 96.0, 96.0,
                 "The death certificate copies remain an estimated $96 passed through at the county's cost.")]
    v2, changes = agent.merge_reply(old, reply, "A-v2", "A")
    assert len(v2) == 1
    assert v2[0]["name"] == "Certified copies of death certificate"
    assert changes[0]["kind"] == "confirmed"


def test_line_diff_statuses():
    reply = [dict(i, quote_id="A-v2") for i in FAKE_DOCS["reply_A_v2.txt"]]
    v2, _ = agent.merge_reply(_v1(), reply, "A-v2", "A")
    rows = {r["name"]: r for r in agent.line_diff(_v1(), v2)}
    assert rows["Crematory charges"]["status"] == "resolved"
    assert rows["Crematory charges"]["v1"] == "Unresolved"
    assert rows["Refrigeration / sheltering of remains"]["status"] == "changed"
    assert rows["Transfer of remains to funeral home"]["status"] == "unchanged"


def test_validate_never_turns_unknown_into_zero():
    items, issues = agent.validate_items(
        [{"name": "x", "price_type": "fixed", "amount_low": None, "amount_high": None, "excerpt": ""}],
        "A-v1", "A", "q.txt")
    assert items[0]["price_type"] == "unknown" and items[0]["amount_low"] is None
    assert len(issues) == 2


def test_provider_from_filename_is_generic():
    assert agent.provider_from_filename("quote_A.txt") == "A"
    assert agent.provider_from_filename("reply_b_alt.txt") == "B"
    assert agent.provider_from_filename("quote_Z9.pdf") == "Z9"
    assert agent.provider_from_filename("notes.txt") is None


def test_fmt_money_unknown_is_unresolved():
    assert agent.fmt_money(None, None) == "Unresolved"
    assert agent.fmt_money(395.0, 395.0) == "$395"
    assert agent.fmt_money(24.0, 48.0) == "$24–$48"


# ---------------------------------------------------------------------------
# Orchestration (real DB + approvals + outbox, fake SIE / memory / persona)
# ---------------------------------------------------------------------------


def _setup_quote(env):
    agent.ingest_wishes()
    res = agent.ingest_document(env["data"] / "quote_A.txt")
    agent.run_analysis()
    return res


def test_ingest_document_writes_db_traces_memory(env):
    res = _setup_quote(env)
    assert res["quote_id"] == "A-v1"
    assert len(db.get_quote_items("A-v1")) == 5
    assert len(db.list_sie_calls()) == 2
    assert any(c[0] == "remember_quote" for c in env["calls"]["remember"])
    assert db.get_quote_items("A-v1")[4]["amount_low"] is None
    assert [w["wish_id"] for w in agent.wishes()] == ["W1", "W2", "W3", "W4"]
    assert agent.wishes()[3]["value"] == 4000.0
    plan = agent.plan_for_quote("A-v1")
    assert plan and plan["unresolved"]  # crematory unresolved, never zero
    actions = {a["action"] for a in db.list_audit()}
    assert {"document_ingested", "analysis_run", "wishes_loaded"} <= actions


def test_clarification_sends_once_and_reply_builds_v2(env):
    _setup_quote(env)
    card = agent.prepare_clarification("A")
    assert card["recipient"] == "arrangements@provider-a.example"
    assert card["body"].startswith(drafting.TEMPLATE_LABEL)
    assert "Crematory charges" in card["body"]
    agent.approve_and_send(card["approval_id"])
    agent.approve_and_send(card["approval_id"])  # retry: no duplicate
    assert len(db.list_outbox()) == 1

    res = agent.ingest_reply(str(env["data"] / "reply_A_v2.txt"), "A")
    assert res["new_quote_id"] == "A-v2"
    qs = {q["id"]: q for q in db.list_quotes()}
    assert "A-v1" in qs and qs["A-v2"]["supersedes_id"] == "A-v1"
    assert len(db.get_quote_items("A-v1")) == 5  # v1 kept unchanged
    assert db.get_quote_items("A-v1")[4]["amount_low"] is None
    v2 = {i["name"]: i for i in db.get_quote_items("A-v2")}
    assert v2["Crematory charges"]["amount_low"] == 395.0
    assert all(p["stale"] for p in db.list_plans("A-v1"))
    assert any(c[0] == "remember_reply" for c in env["calls"]["remember"])
    assert "The reply sets it at $395" in res["explanation"]
    d = agent.latest_reply_diff()
    assert d["new_quote_id"] == "A-v2" and d["diff"]["new_plan"]["known_total"] is not None


def test_card_invalidated_when_quote_changes(env):
    _setup_quote(env)
    card = agent.prepare_clarification("A")
    agent.ingest_reply(str(env["data"] / "reply_A_v2.txt"), "A")
    assert not agent.get_card(card["approval_id"])["valid"]
    with pytest.raises(agent.ApprovalBlocked):
        agent.approve_and_send(card["approval_id"])
    assert db.list_outbox() == []


def test_arrangement_blocked_until_persona_approved(env):
    _setup_quote(env)
    agent.select_quote("A-v1")
    card = agent.prepare_arrangement("A")
    assert card["extra"]["services"]
    with pytest.raises(agent.ApprovalBlocked):
        agent.approve_and_send(card["approval_id"], persona_inquiry_id="inq_1")
    env["calls"]["persona_ok"] = True
    row = agent.approve_and_send(card["approval_id"], persona_inquiry_id="inq_1")
    assert row["display_status"] == "Arrangement request sent — awaiting provider confirmation."
    assert db.list_approvals()[0]["persona_inquiry_id"] == "inq_1"


def test_memory_missing_does_not_block_db(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "memory.cognee_mem", None)  # import -> ImportError
    agent.ingest_document(env["data"] / "quote_A.txt")
    assert len(db.get_quote_items("A-v1")) == 5
    assert agent.memory_skips() >= 1


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------


def test_drafting_template_and_guardrails(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    flags = [{"flag_id": "C-F1", "kind": "stated_requirement", "item_id": None,
              "excerpt": "A casket purchase is required for direct cremation.", "message": "m"}]
    body = drafting.draft_clarification(flags, None, "C")
    assert body.startswith(drafting.TEMPLATE_LABEL)
    assert "alternative-container" in body
    assert not drafting.BANNED.search(body)
    assert not drafting._safe("The fee is $999.", "fee $395")
    assert drafting._safe("The fee is $395.", "fee $395.00")
    assert not drafting._safe("This is illegal.", "")
