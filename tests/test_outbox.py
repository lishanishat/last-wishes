import pytest

import approvals
import db
import outbox


@pytest.fixture(autouse=True)
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LW_DB", "sqlite")
    monkeypatch.setenv("LW_SQLITE_PATH", str(tmp_path / "t.sqlite"))
    db.close_conn()
    db.init_schema()
    db.insert_quote("A", 1)
    yield
    db.close_conn()


def _approved(kind="clarification", persona=None):
    card = approvals.prepare_card(kind, "A-v1", "a@provider.test", "Message body", {"k": "v"})
    return approvals.approve(card["id"], "daughter", persona_inquiry_id=persona)


def _sent_rows():
    return [r for r in db.list_outbox() if r["status"] == "sent"]


def test_send_twice_exactly_one_sent_row():
    card = _approved()
    calls = []
    t = lambda row: calls.append(row["id"])
    r1 = outbox.send(card["id"], transport=t)
    r2 = outbox.send(card["id"], transport=t)
    assert r1["id"] == r2["id"] and r1["status"] == "sent"
    assert len(db.list_outbox()) == 1 and len(_sent_rows()) == 1
    assert len(calls) == 1
    assert approvals.get_card(card["id"])["status"] == "sent"


def test_duplicate_insert_hits_unique_constraint():
    card = _approved()
    key = outbox.idempotency_key(card["id"], card["payload_hash"])
    outbox.send(card["id"])
    with pytest.raises(Exception) as ei:
        db.execute("INSERT INTO outbox (id, approval_id, idempotency_key, status, attempts) VALUES (%s,%s,%s,%s,%s)",
                   ("x", card["id"], key, "queued", 0))
    assert db.is_duplicate_error(ei.value)


def test_transport_fails_then_retry_one_sent_attempts_2():
    card = _approved()
    state = {"n": 0}

    def flaky(row):
        state["n"] += 1
        if state["n"] == 1:
            raise ConnectionError("smtp down")

    with pytest.raises(outbox.OutboxSendFailed) as ei:
        outbox.send(card["id"], transport=flaky)
    assert ei.value.row["status"] == "failed" and ei.value.row["attempts"] == 1
    row = outbox.send(card["id"], transport=flaky)
    assert row["status"] == "sent" and row["attempts"] == 2
    assert len(db.list_outbox()) == 1 and len(_sent_rows()) == 1


def test_quote_changes_after_approval_send_invalidated():
    card = _approved()
    db.insert_quote("A", 2, supersedes_id="A-v1")
    with pytest.raises(approvals.ApprovalInvalidated):
        outbox.send(card["id"])
    assert approvals.get_card(card["id"])["status"] == "invalidated"
    assert db.list_outbox() == []


def test_unapproved_card_cannot_send():
    card = approvals.prepare_card("clarification", "A-v1", "a@provider.test", "Q?")
    with pytest.raises(approvals.ApprovalError):
        outbox.send(card["id"])
    assert db.list_outbox() == []


def test_arrangement_display_status_and_no_purchase_words():
    card = _approved("arrangement", persona="inq_1")
    row = outbox.send(card["id"])
    assert row["display_status"] == "Arrangement request sent — awaiting provider confirmation."
    for r in db.list_outbox():
        s = (r["display_status"] or "").lower()
        assert "purchased" not in s and "booked" not in s


def test_reset_all_clears():
    card = _approved()
    outbox.send(card["id"])
    db.reset_all()
    assert db.list_outbox() == [] and db.list_quotes() == []
