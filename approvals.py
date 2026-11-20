"""Approval cards (LAST_WISHES.md §3, §8 steps 10 and 17).

- Each approval covers exactly one message (recipient + body) for one exact quote version.
- payload_hash = sha256(canonical JSON of {kind, quote_id, recipient, body, extra}).
- If the provider's latest quote version is no longer the card's quote_id, the card is
  invalidated and must be rebuilt (prepare_card again).
- An arrangement approval requires a Persona inquiry id (identity verified upstream).
- Every transition is written to audit_log. Approvals never enforce anything in Cognee.

Statuses: pending -> approved -> sent   |   pending/approved -> invalidated
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import db

KINDS = ("clarification", "arrangement")


class ApprovalError(Exception):
    """Approval refused (bad state, missing identity check, tampered payload, ...)."""


class ApprovalInvalidated(ApprovalError):
    """The quote changed after the card was prepared; prepare a new card."""


def canonical_payload(kind: str, quote_id: str, recipient: str, body: str, extra: Optional[dict]) -> str:
    return json.dumps({"kind": kind, "quote_id": quote_id, "recipient": recipient, "body": body,
                       "extra": extra or {}},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def payload_hash(kind: str, quote_id: str, recipient: str, body: str, extra: Optional[dict]) -> str:
    return hashlib.sha256(canonical_payload(kind, quote_id, recipient, body, extra).encode("utf-8")).hexdigest()


def _card(row: dict) -> dict:
    row = dict(row)
    row["extra"] = db.loads(row.get("extra_json"), {})
    return row


def get_card(approval_id: str) -> Optional[dict]:
    row = db.query_one("SELECT * FROM approvals WHERE id=%s", (approval_id,))
    return _card(row) if row else None


def _require(approval_id: str) -> dict:
    card = get_card(approval_id)
    if not card:
        raise ApprovalError(f"approval {approval_id} not found")
    return card


def prepare_card(kind: str, quote_id: str, recipient: str, body: str, extra: Optional[dict] = None,
                 *, actor: str = "agent") -> dict:
    """Persist a pending approval card for exactly one message. Returns the card dict.

    extra: anything else the reviewer sees and approves (services, totals, provider name...).
    It is part of the hash, so changing it means a different card.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not recipient or not body:
        raise ValueError("recipient and body are required")
    quote = db.get_quote(quote_id)
    if not quote:
        raise ApprovalError(f"quote {quote_id} not found")
    latest = db.latest_quote_version(quote["provider"])
    if latest and latest["id"] != quote_id:
        raise ApprovalInvalidated(
            f"quote {quote_id} is not the latest version for provider {quote['provider']} (latest {latest['id']})")
    extra = extra or {}
    h = payload_hash(kind, quote_id, recipient, body, extra)
    aid = db.new_id("ap")
    db.execute("INSERT INTO approvals (id, kind, quote_id, provider, recipient, body, extra_json, payload_hash, "
               "status, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
               (aid, kind, quote_id, quote["provider"], recipient, body, db.dumps(extra), h, "pending", db.now()))
    db.audit(actor, "approval.prepared", {"approval_id": aid, "kind": kind, "quote_id": quote_id,
                                          "recipient": recipient, "payload_hash": h})
    return get_card(aid)


def _stale_reason(card: dict) -> Optional[str]:
    """None if the card still matches the provider's latest quote and its own hash."""
    latest = db.latest_quote_version(card["provider"])
    if not latest or latest["id"] != card["quote_id"]:
        return f"quote changed: card is for {card['quote_id']}, latest is {latest['id'] if latest else None}"
    h = payload_hash(card["kind"], card["quote_id"], card["recipient"], card["body"], card.get("extra"))
    if h != card["payload_hash"]:
        return "payload hash mismatch (card content changed after it was prepared)"
    return None


def is_valid(card: dict | str) -> bool:
    """True if not invalidated and still bound to the provider's latest quote with an intact hash."""
    if isinstance(card, str):
        card = get_card(card)
        if not card:
            return False
    if card.get("status") == "invalidated":
        return False
    return _stale_reason(card) is None


def invalidate(approval_id: str, reason: str, *, actor: str = "system") -> dict:
    db.execute("UPDATE approvals SET status=%s, invalidated_at=%s, invalid_reason=%s WHERE id=%s",
               ("invalidated", db.now(), reason, approval_id))
    db.audit(actor, "approval.invalidated", {"approval_id": approval_id, "reason": reason})
    return get_card(approval_id)


def check_still_valid(card: dict, *, actor: str = "system") -> None:
    """Invalidate + raise ApprovalInvalidated if the card no longer matches the latest quote."""
    reason = _stale_reason(card)
    if reason:
        invalidate(card["id"], reason, actor=actor)
        raise ApprovalInvalidated(reason)


def approve(approval_id: str, approved_by: str, persona_inquiry_id: Optional[str] = None) -> dict:
    """pending -> approved. Re-validates the quote version first.

    Raises ApprovalInvalidated if the quote changed (card is marked invalidated),
    ApprovalError if not pending or if an arrangement lacks persona_inquiry_id.
    The caller must have verified the Persona inquiry status == approved before passing its id.
    """
    card = _require(approval_id)
    if card["status"] != "pending":
        raise ApprovalError(f"approval {approval_id} is {card['status']}, not pending")
    if not approved_by:
        raise ApprovalError("approved_by is required")
    check_still_valid(card, actor=approved_by)
    if card["kind"] == "arrangement" and not persona_inquiry_id:
        db.audit(approved_by, "approval.refused", {"approval_id": approval_id,
                                                   "reason": "arrangement requires persona_inquiry_id"})
        raise ApprovalError("Arrangement approval requires a verified Persona inquiry id.")
    n = db.execute("UPDATE approvals SET status=%s, approved_by=%s, persona_inquiry_id=%s, approved_at=%s "
                   "WHERE id=%s AND status=%s",
                   ("approved", approved_by, persona_inquiry_id, db.now(), approval_id, "pending"))
    if n != 1:
        raise ApprovalError(f"approval {approval_id} changed state concurrently")
    db.audit(approved_by, "approval.approved", {"approval_id": approval_id, "kind": card["kind"],
                                                "quote_id": card["quote_id"],
                                                "persona_inquiry_id": persona_inquiry_id})
    return get_card(approval_id)


def list_cards(status: Optional[str] = None) -> list[dict]:
    return db.list_approvals(status)
