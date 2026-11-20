"""Idempotent outbox (LAST_WISHES.md §3 "Send once", §8 steps 10 and 18).

send(approval_id) -> outbox row.
- Requires an approved, still-valid approval (quote version re-checked here).
- idempotency_key = sha256(approval_id + payload_hash); the outbox PRIMARY KEY on it
  (rowstore, SHARD KEY(idempotency_key) on SingleStore) makes a second row impossible.
- A row is claimed atomically (UPDATE ... WHERE status IN ('queued','failed')) before the
  transport is called, so concurrent/duplicate sends never call the transport twice.
- Transport failure -> status 'failed', attempts+1, OutboxSendFailed raised. Calling send()
  again retries the SAME row; a sent row is returned as-is.
- Default transport is the sandbox: no network; the outbox row is the record.
- The agent never pays: the arrangement display status is fixed below.
"""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

import approvals
import db

ARRANGEMENT_SENT = "Arrangement request sent — awaiting provider confirmation."
CLARIFICATION_SENT = "Clarification sent — awaiting provider reply."
_FORBIDDEN = ("purchased", "booked")

Transport = Callable[[dict], object]


class OutboxSendFailed(Exception):
    def __init__(self, row: dict, cause: Exception):
        super().__init__(f"send failed (attempt {row.get('attempts')}): {cause}")
        self.row = row
        self.cause = cause


def sandbox_transport(row: dict) -> dict:
    """No network. The outbox row itself is the sent record."""
    return {"transport": "sandbox", "recipient": row["recipient"]}


def idempotency_key(approval_id: str, payload_hash: str) -> str:
    return hashlib.sha256(f"{approval_id}{payload_hash}".encode("utf-8")).hexdigest()


def display_status_for(kind: str) -> str:
    s = ARRANGEMENT_SENT if kind == "arrangement" else CLARIFICATION_SENT
    assert not any(w in s.lower() for w in _FORBIDDEN)
    return s


def get_row(key: str) -> Optional[dict]:
    return db.query_one("SELECT * FROM outbox WHERE idempotency_key=%s", (key,))


def get_by_approval(approval_id: str) -> Optional[dict]:
    return db.query_one("SELECT * FROM outbox WHERE approval_id=%s", (approval_id,))


def _ensure_row(card: dict, key: str) -> dict:
    """INSERT the queued row; on duplicate key return the existing row (no second row ever)."""
    try:
        db.execute("INSERT INTO outbox (id, approval_id, idempotency_key, kind, recipient, body, status, attempts, "
                   "created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                   ("ob-" + key[:16], card["id"], key, card["kind"], card["recipient"], card["body"],
                    "queued", 0, db.now()))
        db.audit("outbox", "outbox.queued", {"approval_id": card["id"], "idempotency_key": key})
    except Exception as e:
        if not db.is_duplicate_error(e):
            raise
    row = get_row(key)
    assert row is not None
    return row


def send(approval_id: str, transport: Optional[Transport] = None, *, actor: str = "outbox") -> dict:
    """Send the one message an approval covers, at most once. Returns the outbox row."""
    transport = transport or sandbox_transport
    card = approvals.get_card(approval_id)
    if not card:
        raise approvals.ApprovalError(f"approval {approval_id} not found")
    key = idempotency_key(approval_id, card["payload_hash"])

    existing = get_row(key)
    if existing and existing["status"] == "sent":
        db.audit(actor, "outbox.duplicate_suppressed", {"approval_id": approval_id, "idempotency_key": key})
        return existing

    if card["status"] != "approved":
        raise approvals.ApprovalError(f"approval {approval_id} is {card['status']}, not approved")
    approvals.check_still_valid(card, actor=actor)  # invalidates + raises if the quote changed

    row = _ensure_row(card, key)
    if row["status"] == "sent":
        return row

    # Atomic claim: only one caller moves queued/failed -> sending and calls the transport.
    claimed = db.execute("UPDATE outbox SET status=%s, attempts=attempts+1 "
                         "WHERE idempotency_key=%s AND status IN (%s,%s)",
                         ("sending", key, "queued", "failed"))
    if claimed != 1:
        return get_row(key)  # someone else is sending / already sent
    row = get_row(key)

    try:
        transport(dict(row))
    except Exception as e:
        db.execute("UPDATE outbox SET status=%s, last_error=%s WHERE idempotency_key=%s",
                   ("failed", repr(e)[:2000], key))
        row = get_row(key)
        db.audit(actor, "outbox.failed", {"approval_id": approval_id, "attempts": row["attempts"],
                                          "error": repr(e)[:500]})
        raise OutboxSendFailed(row, e) from e

    status_text = display_status_for(card["kind"])
    db.execute("UPDATE outbox SET status=%s, sent_at=%s, display_status=%s, last_error=NULL "
               "WHERE idempotency_key=%s", ("sent", db.now(), status_text, key))
    db.execute("UPDATE approvals SET status=%s WHERE id=%s AND status=%s", ("sent", approval_id, "approved"))
    row = get_row(key)
    db.audit(actor, "outbox.sent", {"approval_id": approval_id, "kind": card["kind"], "recipient": card["recipient"],
                                    "attempts": row["attempts"], "display_status": status_text})
    return row
