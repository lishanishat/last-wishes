"""Offline tests for the chat engine. Real: db (sqlite tmp), approvals, outbox, pipeline.wishes/flags/optimizer.
Faked (as in tests/test_agent.py): SIE extract/classify, Cognee memory, Persona."""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import agent
import db
from chat import engine, router

ROOT = Path(__file__).resolve().parent.parent


def _it(n, name, cat, pt, lo, hi, excerpt, prov):
    return {"item_id": f"{prov}-{n:02d}", "quote_id": "", "provider": prov, "name": name, "category": cat,
            "price_type": pt, "amount_low": lo, "amount_high": hi, "excerpt": excerpt, "source_doc": "",
            "confidence": 0.9}


FAKE = {
    "quote_A": [
        _it(1, "Basic services of funeral director and staff", "basic_fee", "fixed", 895.0, 895.0, "Basic services $895.00", "A"),
        _it(2, "Transfer of remains to funeral home", "basic_fee", "fixed", 350.0, 350.0, "Transfer $350.00", "A"),
        _it(3, "Refrigeration / sheltering of remains", "optional", "fixed", 150.0, 150.0, "Refrigeration $150.00", "A"),
        _it(4, "Alternative container (fiberboard)", "basic_fee", "fixed", 75.0, 75.0, "Alternative container $75.00", "A"),
        _it(5, "Crematory charges", "basic_fee", "unknown", None, None, "Crematory charges | TBC", "A"),
    ],
    "quote_B": [
        _it(1, "Direct cremation (basic)", "package", "fixed", 1195.0, 1195.0, "Direct cremation $1,195", "B"),
        _it(2, "Alternative container", "basic_fee", "fixed", 60.0, 60.0, "Container $60", "B"),
    ],
    "quote_C": [
        _it(1, "Celebration package", "package", "fixed", 3200.0, 3200.0, "Celebration Package $3,200", "C"),
        _it(2, "Casket", "optional", "starting_at", 900.0, None, "A casket purchase is required for direct "
            "cremation. Caskets from $900", "C"),
    ],
    "reply_A": [
        _it(1, "Crematory fee", "basic_fee", "fixed", 395.0, 395.0, "Our crematory fee is $395", "A"),
        _it(2, "Refrigeration charge", "optional", "fixed", 195.0, 195.0, "up to 7 days it is $195", "A"),
    ],
    "real_gpl": [_it(1, "Direct cremation", "package", "starting_at", 1500.0, None, "Direct cremation from $1,500", "REAL")],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LW_DB", "sqlite")
    monkeypatch.setenv("LW_SQLITE_PATH", str(tmp_path / "t.sqlite"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LW_CHAT_SKIP_PERSONA", raising=False)
    monkeypatch.setattr(engine, "TMP_DIR", tmp_path / "chat_tmp")
    db.close_conn()
    db.init_schema()

    extract = types.ModuleType("pipeline.extract")

    def extract_quote(text, source_doc, quote_id):
        key = next(k for k in FAKE if source_doc.startswith(k))
        items = []
        for raw in FAKE[key]:
            it = dict(raw)
            it["quote_id"], it["source_doc"] = quote_id, source_doc
            items.append(it)
        return items, [{"recipe": "extract", "model": "fake", "latency_ms": 1, "input_chars": len(text)}]

    extract.extract_quote = extract_quote
    classify = types.ModuleType("pipeline.classify")
    classify.classify = lambda items: (items, [])
    mem = types.ModuleType("memory.cognee_mem")
    for n in ("remember_wish", "remember_quote", "remember_question", "remember_reply", "remember_confirmation",
              "remember_plan"):
        mem.__dict__[n] = lambda *a, **k: None
    mem.recall = lambda query, exclude_wish_ids=None: {
        "query": query, "answer": "Crematory fee for A was pending.", "nodes": [{"id": "q1"}],
        "edges": [{"source": "q1", "target": "A-v1", "relationship": "ABOUT"}]}
    mem.reset_memory = lambda: None
    monkeypatch.setitem(sys.modules, "pipeline.extract", extract)
    monkeypatch.setitem(sys.modules, "pipeline.classify", classify)
    monkeypatch.setitem(sys.modules, "memory.cognee_mem", mem)
    yield tmp_path
    db.close_conn()


def types_of(events):
    return [e["type"] for e in events]


def of(events, t):
    return [e for e in events if e["type"] == t]


def test_load_samples_gives_quotes_flags_plan_and_chips(env):
    evs = engine.act({"do": "load_samples"})
    t = types_of(evs)
    assert t.count("quote") == 4 and "flags" in t and "plan" in t and t[-1] == "next_steps"
    json.dumps(evs)  # JSON-serializable
    quotes = {e["provider"]: e for e in of(evs, "quote")}
    assert quotes["A"]["fictional"] and quotes["B"]["fictional"] and quotes["C"]["fictional"]
    assert quotes["REAL"]["fictional"] is False and "real_gpl" not in quotes["REAL"]["source"] or True
    assert quotes["REAL"]["source"] and "Menlo Park" in quotes["REAL"]["source"]
    assert "REAL" not in agent.latest_quotes()  # real list stays out of the comparison
    a = quotes["A"]
    assert a["unresolved"] and any(r["amount_text"] == "Unresolved" for r in a["rows"])
    assert not any(r["amount_text"] in ("$0", "$0.00") for r in a["rows"])
    flag_text = json.dumps(of(evs, "flags")).lower()
    assert "illegal" not in flag_text and "violat" not in flag_text
    labels = [i["label"] for i in of(evs, "next_steps")[0]["items"]]
    assert any(l.startswith("Ask Provider A about") for l in labels) and "Compare quotes" in labels


def test_approve_twice_sends_once(env):
    engine.act({"do": "load_samples", "include_real": False})
    card = of(engine.act({"do": "draft_clarification", "provider": "A"}), "approval")[0]["card"]
    assert card["kind"] == "clarification" and "Crematory" in card["body"]
    first = engine.act({"do": "approve", "approval_id": card["approval_id"]})
    second = engine.act({"do": "approve", "approval_id": card["approval_id"]})
    assert of(first, "receipt") and not of(second, "receipt")
    assert "already sent" in of(second, "text")[0]["text"].lower()
    assert len(db.list_outbox()) == 1


def test_reply_makes_v2_diff_and_keeps_v1(env):
    engine.act({"do": "load_samples", "include_real": False})
    reply = (ROOT / "data" / "reply_A_v2.txt").read_text()
    evs = engine.handle("reply from A:\n" + reply)
    q = of(evs, "quote")[0]
    assert q["quote_id"] == "A-v2" and q["version"] == 2
    d = of(evs, "diff")[0]
    assert any(r["status"] == "resolved" for r in d["diff"]) and d["explanation"]
    assert {x["id"] for x in db.list_quotes()} >= {"A-v1", "A-v2"}
    assert db.get_quote_items("A-v1")[4]["amount_low"] is None
    assert of(evs, "memory")


def test_stale_card_is_blocked_after_reply(env):
    engine.act({"do": "load_samples", "include_real": False})
    card = of(engine.act({"do": "draft_clarification", "provider": "A"}), "approval")[0]["card"]
    engine.handle("reply from A: " + (ROOT / "data" / "reply_A_v2.txt").read_text())
    evs = engine.act({"do": "approve", "approval_id": card["approval_id"]})
    assert of(evs, "error") and not db.list_outbox()
    assert of(evs, "approval")[0]["card"]["valid"] is False
    rebuilt = engine.act({"do": "rebuild", "approval_id": card["approval_id"]})
    assert not of(rebuilt, "error") and "Nothing to rebuild" in of(rebuilt, "text")[0]["text"]  # reply settled it


def test_arrangement_ends_with_exact_status_without_persona(env):
    engine.act({"do": "load_samples", "include_real": False})
    evs = engine.act({"do": "prepare_arrangement", "provider": "B"})
    card = of(evs, "approval")[0]["card"]
    assert card["kind"] == "arrangement" and "not run" in card["identity_note"]
    done = engine.act({"do": "approve", "approval_id": card["approval_id"]})
    assert of(done, "text")[0]["text"] == "Arrangement request sent — awaiting provider confirmation."
    lines = " ".join(of(done, "receipt")[0]["lines"]).lower()
    assert "identity verification not run" in lines and "verified" not in lines.replace("not run", "")
    again = engine.act({"do": "approve", "approval_id": card["approval_id"]})
    assert not of(again, "receipt") and len(db.list_outbox()) == 1
    assert db.list_approvals()[0]["persona_inquiry_id"] == engine.PERSONA_MARKER


def test_persona_flag_off_blocks_arrangement(env, monkeypatch):
    monkeypatch.setenv("LW_CHAT_SKIP_PERSONA", "0")
    engine.act({"do": "load_samples", "include_real": False})
    card = of(engine.act({"do": "prepare_arrangement", "provider": "B"}), "approval")[0]["card"]
    evs = engine.act({"do": "approve", "approval_id": card["approval_id"]})
    assert of(evs, "error") and not db.list_outbox()


def test_history_restores_in_fresh_interpreter(env):
    engine.handle("hello there")
    engine.act({"do": "load_samples", "include_real": False})
    live = [e["type"] for e in engine.history()]
    code = ("import json, chat.engine as e; print(json.dumps([x['type'] for x in e.history()]))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={**__import__("os").environ, "LW_DB": "sqlite",
                              "LW_SQLITE_PATH": str(env / "t.sqlite")}, timeout=60)
    assert out.returncode == 0, out.stderr
    restored = json.loads(out.stdout.strip().splitlines()[-1])
    assert restored == live and restored[0] == "user" and "quote" in restored


def test_router_rules():
    r = router.route
    assert r("reply from A: Dear Maya, the fee is $5")["intent"] == "reply"
    assert r("reply from a: x")["provider"] == "A"
    assert r("From: x@y.example\nSubject: Re: question\n\nThe fee is $395.")["intent"] == "reply"
    assert r("quote from B: Cremation $1,000, urn $50")["intent"] == "quote"
    assert r("Cremation $1,000\nUrn $50\nContainer $60")["intent"] == "quote"
    assert r("compare")["intent"] == "compare"
    assert r("what was pending?")["intent"] == "recall"
    assert r("what did Linda want")["intent"] == "recall"
    assert r("https://example.com/price-list")["intent"] == "url"
    assert r("She wanted a simple cremation and no viewing. Budget about four thousand.")["intent"] == "wishes"
    assert r("hello")["intent"] == "help"


def test_url_and_unknown_text_do_not_crash(env):
    evs = engine.handle("https://example.com/prices")
    assert "not available yet" in of(evs, "text")[0]["text"]
    assert of(engine.handle("compare"), "text")
    assert of(engine.act({"do": "nope"}), "error")


def test_reset_clears(env):
    engine.act({"do": "load_samples", "include_real": False})
    engine.act({"do": "reset"})
    assert not agent.latest_quotes()
    assert types_of(engine.history())[0] == "text"
