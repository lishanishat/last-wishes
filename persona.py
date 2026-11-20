"""Persona sandbox identity check (spec §14, pipeline step 16).

Before Approval #2 the daughter completes a Persona hosted-flow inquiry.
The app polls the inquiry and only unblocks Approval #2 when the status is
exactly "approved".

Endpoints (Persona API reference, docs.withpersona.com):
  POST /api/v1/inquiries                                   create an inquiry
  GET  /api/v1/inquiries/{inquiry-id}                      retrieve an inquiry
  POST /api/v1/inquiries/{inquiry-id}/generate-one-time-link
  POST /api/v1/inquiries/{inquiry-id}/perform-simulate-actions  (sandbox only)
"""
from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

PERSONA_COPY = "Persona verifies who is approving — not legal authority."

BASE_URL = "https://api.withpersona.com/api/v1"
# Pinned so response shapes don't drift; the docs list this as the current default.
PERSONA_VERSION = os.getenv("PERSONA_VERSION", "2026-09-29")
TIMEOUT = 15  # seconds, applied to every request

# Exact inquiry status values from the Retrieve an Inquiry reference.
# Persona notes new values may be added, so unknown strings pass through as-is.
STATUSES = (
    "created",
    "pending",
    "completed",
    "expired",
    "failed",
    "needs_review",
    "approved",
    "declined",
)
APPROVED = "approved"
TERMINAL = ("approved", "declined", "failed", "expired")

_session = requests.Session()


def _api_key() -> str:
    key = os.getenv("PERSONA_API_KEY")
    if not key:
        raise RuntimeError(
            "PERSONA_API_KEY is not set. Add your Persona sandbox API key to .env "
            "(see .env.example)."
        )
    return key


def _template_id() -> str:
    tid = os.getenv("PERSONA_TEMPLATE_ID")
    if not tid:
        raise RuntimeError(
            "PERSONA_TEMPLATE_ID is not set. Add your Persona inquiry template id "
            "(itmpl_... or tmpl_...) to .env."
        )
    return tid


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Persona-Version": PERSONA_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Key-Inflection": "kebab",
    }


def _request(method: str, path: str, json: dict | None = None) -> dict:
    headers = _headers()  # raises before any network call if the key is missing
    resp = _session.request(
        method, f"{BASE_URL}{path}", headers=headers, json=json, timeout=TIMEOUT
    )
    if resp.status_code >= 400:
        try:
            errors = resp.json().get("errors")
        except ValueError:
            errors = resp.text[:300]
        raise RuntimeError(
            f"Persona {method} {path} failed with HTTP {resp.status_code}: {errors}"
        )
    return resp.json()


def _template_attr(tid: str) -> str:
    # Docs: pass exactly one of template-id (tmpl_), inquiry-template-id (itmpl_),
    # or inquiry-template-version-id (itmplv_).
    if tid.startswith("itmplv_"):
        return "inquiry-template-version-id"
    if tid.startswith("tmpl_"):
        return "template-id"
    return "inquiry-template-id"


def create_inquiry(
    reference_id: str, name_first: str | None = None, name_last: str | None = None
) -> dict:
    """Create a sandbox inquiry and return {"inquiry_id", "hosted_url"}.

    hosted_url is a Persona one-time link (https://withpersona.com/verify?code=...)
    that opens the hosted flow for this exact inquiry.
    """
    tid = _template_id()
    attributes: dict = {_template_attr(tid): tid}
    fields = {}
    if name_first:
        fields["name-first"] = name_first
    if name_last:
        fields["name-last"] = name_last
    if fields:
        attributes["fields"] = fields

    body = {
        "data": {"attributes": attributes},
        "meta": {
            # data.attributes.reference-id is deprecated in favour of this.
            "auto-create-account-reference-id": reference_id,
            "auto-create-one-time-link": True,
        },
    }
    payload = _request("POST", "/inquiries", json=body)
    inquiry_id = payload["data"]["id"]
    meta = payload.get("meta") or {}
    hosted_url = meta.get("one-time-link") or meta.get("one-time-link-short")
    if not hosted_url:
        hosted_url = generate_one_time_link(inquiry_id)
    return {"inquiry_id": inquiry_id, "hosted_url": hosted_url}


def generate_one_time_link(inquiry_id: str) -> str:
    """Fresh hosted-flow link for an existing inquiry (e.g. after the old one expired)."""
    payload = _request("POST", f"/inquiries/{inquiry_id}/generate-one-time-link", json={})
    meta = payload.get("meta") or {}
    link = meta.get("one-time-link") or meta.get("one-time-link-short")
    if not link:
        raise RuntimeError(f"Persona returned no one-time link for {inquiry_id}")
    return link


def parse_status(payload: dict) -> str:
    """Pull data.attributes.status out of an inquiry response."""
    try:
        status = payload["data"]["attributes"]["status"]
    except (KeyError, TypeError):
        raise RuntimeError("Persona response has no data.attributes.status") from None
    if not isinstance(status, str) or not status:
        raise RuntimeError(f"Persona returned an invalid status: {status!r}")
    return status


def get_status(inquiry_id: str) -> str:
    """Inquiry status exactly as Persona returns it (see STATUSES)."""
    return parse_status(_request("GET", f"/inquiries/{inquiry_id}"))


def is_approved(inquiry_id: str) -> bool:
    """True only when Persona reports status "approved"."""
    return get_status(inquiry_id) == APPROVED


def simulate_approve(inquiry_id: str) -> str:
    """Sandbox only: move the inquiry to "approved" via Perform Simulate Actions.

    Fires inquiry.approved just like a real approval. Persona rejects this call
    for non-sandbox inquiries. Returns the resulting status.
    """
    body = {"meta": {"simulate-actions": [{"type": "approve_inquiry"}]}}
    payload = _request(
        "POST", f"/inquiries/{inquiry_id}/perform-simulate-actions", json=body
    )
    try:
        return parse_status(payload)
    except RuntimeError:
        return get_status(inquiry_id)
