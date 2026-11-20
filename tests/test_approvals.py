import pytest

import approvals
import db


@pytest.fixture(autouse=True)
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LW_DB", "sqlite")
    monkeypatch.setenv("LW_SQLITE_PATH", str(tmp_path / "t.sqlite"))
    db.close_conn()
    db.init_schema()
    db.insert_quote("A", 1)
    yield
    db.close_conn()


def test_prepare_persists_pending_with_hash():
    card = approvals.prepare_card("clarification", "A-v1", "a@provider.test", "What is the crematory fee?")
    assert card["status"] == "pending"
    assert card["payload_hash"] == approvals.payload_hash(
        "clarification", "A-v1", "a@provider.test", "What is the crematory fee?", {})
    assert approvals.is_valid(card)
    assert any(a["action"] == "approval.prepared" for a in db.list_audit())


def test_hash_is_canonical():
    h1 = approvals.payload_hash("arrangement", "A-v1", "r", "b", {"x": 1, "y": 2})
    h2 = approvals.payload_hash("arrangement", "A-v1", "r", "b", {"y": 2, "x": 1})
    assert h1 == h2
    assert h1 != approvals.payload_hash("arrangement", "A-v1", "r", "b2", {"x": 1, "y": 2})


def test_new_quote_version_invalidates_on_approve():
    card = approvals.prepare_card("clarification", "A-v1", "a@provider.test", "Q?")
    db.insert_quote("A", 2, supersedes_id="A-v1")
    assert not approvals.is_valid(card["id"])
    with pytest.raises(approvals.ApprovalInvalidated):
        approvals.approve(card["id"], "daughter")
    after = approvals.get_card(card["id"])
    assert after["status"] == "invalidated" and after["invalidated_at"]
    assert any(a["action"] == "approval.invalidated" for a in db.list_audit())


def test_arrangement_requires_persona():
    card = approvals.prepare_card("arrangement", "A-v1", "a@provider.test", "Please arrange.",
                                  {"services": ["A-01"]})
    with pytest.raises(approvals.ApprovalError):
        approvals.approve(card["id"], "daughter")
    assert approvals.get_card(card["id"])["status"] == "pending"
    ok = approvals.approve(card["id"], "daughter", persona_inquiry_id="inq_sandbox_1")
    assert ok["status"] == "approved" and ok["persona_inquiry_id"] == "inq_sandbox_1"


def test_cannot_approve_twice():
    card = approvals.prepare_card("clarification", "A-v1", "a@provider.test", "Q?")
    approvals.approve(card["id"], "daughter")
    with pytest.raises(approvals.ApprovalError):
        approvals.approve(card["id"], "daughter")


def test_prepare_on_old_version_refused():
    db.insert_quote("A", 2, supersedes_id="A-v1")
    with pytest.raises(approvals.ApprovalInvalidated):
        approvals.prepare_card("clarification", "A-v1", "a@provider.test", "Q?")
