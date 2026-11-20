"""Tests for memory/cognee_mem.py against a real (temporary) Cognee store.

Offline: graph + fastembed embeddings only; the LLM semantic layer is disabled
(LW_COGNIFY=0) and answers use the graph-only path, so no API key is needed.
Run:  .venv/bin/python -m pytest tests/test_memory.py -q
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="lw_cognee_test_"))
TEST_ENV = {
    "SYSTEM_ROOT_DIRECTORY": str(_TMP / ".cognee_system"),
    "DATA_ROOT_DIRECTORY": str(_TMP / ".cognee_data"),
    "CACHE_ROOT_DIRECTORY": str(_TMP / ".cognee_cache"),
    "LW_COGNIFY": "0",
}
for _k, _v in TEST_ENV.items():  # set before the module (and cognee) is imported
    os.environ.setdefault(_k, _v)

from memory import cognee_mem as mem  # noqa: E402

ITEMS_A1 = [
    {"item_id": "A-01", "quote_id": "A-v1", "provider": "A", "name": "Basic services",
     "category": "basic_fee", "price_type": "fixed", "amount_low": 895.0, "amount_high": 895.0,
     "excerpt": "Basic services ... $895", "source_doc": "quote_A.txt", "confidence": 0.9},
]
ITEMS_A2 = ITEMS_A1 + [
    {"item_id": "A-03", "quote_id": "A-v2", "provider": "A", "name": "Crematory fee",
     "category": "cash_advance", "price_type": "fixed", "amount_low": 425.0, "amount_high": 425.0,
     "excerpt": "the crematory charge is $425", "source_doc": "reply_A_v2.txt", "confidence": 0.9},
]
ITEMS_C1 = [
    {"item_id": "C-07", "quote_id": "C-v1", "provider": "C", "name": "Public viewing and flowers",
     "category": "optional", "price_type": "fixed", "amount_low": 900.0, "amount_high": 900.0,
     "excerpt": "Viewing package with floral tribute $900", "source_doc": "quote_C.txt",
     "confidence": 0.9},
]


def _seed():
    mem.reset_memory()
    mem.remember_wish("Cremation, keep it simple", "wishes_linda.txt#1", wish_id="W1")
    mem.remember_wish("No public viewing", "wishes_linda.txt#2", wish_id="W2")
    mem.remember_wish("Please avoid unnecessary extras", "wishes_linda.txt#3", wish_id="W3",
                      confirmed_by="daughter")
    mem.remember_confirmation("daughter", ["W1", "W2"])
    mem.remember_quote("A-v1", "A", 1, ITEMS_A1)
    mem.remember_quote("C-v1", "C", 1, ITEMS_C1)
    mem.remember_question("Q1", "A-v1", "crematory fee")


@pytest.fixture(scope="module")
def seeded():
    _seed()
    return True


def _by_type(snap, t):
    return [n for n in snap["nodes"] if n["type"] == t]


def _rels(snap):
    labels = {n["id"]: n for n in snap["nodes"]}
    return {(labels[e["source"]]["type"], e["relationship"], labels[e["target"]]["type"])
            for e in snap["edges"]}


def test_wish_ids_and_dedupe(seeded):
    assert mem.remember_wish("No public viewing", "wishes_linda.txt#2") == "W2"  # same text
    snap = mem.graph_snapshot()
    assert sorted(n["props"]["wish_id"] for n in _by_type(snap, "Wish")) == ["W1", "W2", "W3"]


def test_before_reply_graph(seeded):
    snap = mem.graph_snapshot()
    rels = _rels(snap)
    for r in [("Person", "STATED", "Wish"), ("Wish", "SOURCED_FROM", "Document"),
              ("FamilyMember", "CONFIRMED", "Wish"), ("FamilyMember", "HAS_ROLE", "Role"),
              ("Provider", "OFFERS", "Quote"), ("Quote", "CONTAINS", "LineItem"),
              ("Question", "ABOUT", "LineItem"), ("Quote", "OMITS", "LineItem")]:
        assert r in rels, r
    (q,) = _by_type(snap, "Question")
    assert q["props"]["status"] == "pending"
    unlisted = [n for n in _by_type(snap, "LineItem") if n["props"].get("status") == "unlisted"]
    assert [n["props"]["name"] for n in unlisted] == ["crematory fee"]
    assert "amount_low" not in unlisted[0]["props"]  # unknown stays None, never 0


def test_recall_pending_question_and_wish(seeded):
    res = mem.recall("What was pending with Provider A?", use_llm=False)
    assert res["query"] == "What was pending with Provider A?"
    assert set(res) >= {"answer", "nodes", "edges"}
    types = {n["type"] for n in res["nodes"]}
    assert {"Question", "Wish"} <= types
    assert res["meta"]["search_edges"] > 0  # Cognee's own retrieval returned edges
    q = next(n for n in res["nodes"] if n["type"] == "Question")
    assert q["props"]["status"] == "pending" and q["props"]["item_name"] == "crematory fee"
    ids = {n["id"] for n in res["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in res["edges"])
    assert "Q1" in res["answer"] and "W3" in res["answer"]


def test_counterfactual_drops_wish(seeded):
    w3 = str(mem.Wish.id_for("W3"))
    res = mem.recall("Should we choose Provider C's viewing and flowers?",
                     exclude_wish_ids=["W3"], use_llm=False)
    assert res["excluded_wish_ids"] == ["W3"]
    assert w3 not in {n["id"] for n in res["nodes"]}
    assert all(w3 not in (e["source"], e["target"]) for e in res["edges"])
    assert "avoid unnecessary extras" not in res["answer"].lower()
    full = mem.recall("Should we choose Provider C's viewing and flowers?", use_llm=False)
    assert w3 in {n["id"] for n in full["nodes"]}


def test_reply_v2_and_plan(seeded):
    mem.remember_quote("A-v2", "A", 2, ITEMS_A2, supersedes="A-v1")
    mem.remember_reply("R1", "Q1", "A-v2")
    mem.remember_plan({"plan_id": "P1", "quote_id": "A-v2", "items": ["A-01", "A-03"],
                       "known_total": 1320.0, "estimated_low": 0.0, "estimated_high": None,
                       "unresolved": [], "not_needed": [], "wishes_satisfied": ["W1", "W2", "W3"]})
    snap = mem.graph_snapshot()
    rels = _rels(snap)
    for r in [("Quote", "SUPERSEDES", "Quote"), ("Reply", "ANSWERS", "Question"),
              ("Reply", "PRODUCED", "Quote"), ("Reply", "RESOLVES", "LineItem"),
              ("Plan", "BASED_ON", "Quote"), ("Plan", "HONORS", "Wish")]:
        assert r in rels, r
    assert {n["props"]["quote_id"] for n in _by_type(snap, "Quote")} >= {"A-v1", "A-v2"}  # v1 kept
    (q,) = _by_type(snap, "Question")
    assert q["props"]["status"] == "answered" and q["props"]["answered_by"] == "R1"
    honors = [e for e in snap["edges"] if e["relationship"] == "HONORS"]
    assert len(honors) == 3


def test_unknown_references_raise(seeded):
    with pytest.raises(KeyError):
        mem.remember_question("Q9", "Z-v1", "anything")
    with pytest.raises(KeyError):
        mem.remember_quote("Z-v2", "Z", 2, [], supersedes="Z-v1")


def test_sync_wrapper_inside_running_loop(seeded):
    async def inner():
        return mem.recall("What did Linda want?", use_llm=False)

    res = asyncio.run(inner())
    assert any(n["type"] == "Wish" for n in res["nodes"])


def test_recall_survives_process_restart():
    """Write in one process, recall in a second fresh process (no shared memory)."""
    env = {**os.environ, **TEST_ENV}
    env["SYSTEM_ROOT_DIRECTORY"] = str(_TMP / "restart" / ".cognee_system")
    env["DATA_ROOT_DIRECTORY"] = str(_TMP / "restart" / ".cognee_data")
    env["CACHE_ROOT_DIRECTORY"] = str(_TMP / "restart" / ".cognee_cache")
    writer = ("from tests.test_memory import _seed; _seed()")
    subprocess.run([sys.executable, "-c", writer], cwd=ROOT, env=env, check=True,
                   capture_output=True, timeout=600)
    reader = ("import json; from memory import cognee_mem as m; "
              "r = m.recall('What was pending with Provider A?', use_llm=False); "
              "print('@@' + json.dumps(r))")
    out = subprocess.run([sys.executable, "-c", reader], cwd=ROOT, env=env, check=True,
                         capture_output=True, text=True, timeout=600).stdout
    res = json.loads(out.split("@@", 1)[1])
    q = [n for n in res["nodes"] if n["type"] == "Question"]
    assert q and q[0]["props"]["status"] == "pending"
    assert any(n["type"] == "Wish" and n["props"].get("stated_by") == "Linda" for n in res["nodes"])
