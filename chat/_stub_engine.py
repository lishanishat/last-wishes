"""Dev-only stand-in for chat.engine. Used only if `import chat.engine` fails or LW_CHAT_STUB=1."""
from __future__ import annotations

_LOG: list = []

IS_STUB = True


def _quote():
    return {"type": "quote", "provider": "A", "quote_id": "A-v1", "version": 1, "fictional": True,
            "source": "quote_A.txt",
            "rows": [
                {"name": "Basic services", "category": "professional", "price_type": "fixed",
                 "amount_text": "$2,100", "excerpt": ""},
                {"name": "Cremation", "category": "cremation", "price_type": "unknown",
                 "amount_text": "Unresolved", "excerpt": ""},
                {"name": "Casket (required)", "category": "merchandise", "price_type": "starting_at",
                 "amount_text": "from $995", "excerpt": ""},
                {"name": "Embalming", "category": "preparation", "price_type": "fixed",
                 "amount_text": "$650", "excerpt": ""}],
            "known_total": 2750, "estimated_low": 2750, "estimated_high": None, "unresolved": ["Cremation"]}


def _flags():
    return {"type": "flags", "flags": [{
        "flag_id": "f1", "quote_id": "A-v1", "item_id": "A-3", "kind": "stated_requirement",
        "excerpt": "A casket is required for all cremations at our facility.",
        "reference": "FTC Funeral Rule: a provider may not require a casket for direct cremation; an alternative container must be offered.",
        "message": "This statement needs clarification with the provider."}]}


def _plan():
    return {"type": "plan", "plan": {"quote_id": "A-v1", "known_total": 2100, "estimated_low": 2100,
            "estimated_high": None, "unresolved": ["Cremation"],
            "not_needed": [{"name": "Embalming", "savings": 650}]},
            "note": "Provider A is not ranked lowest because one charge is unresolved."}


def _approval():
    return {"type": "approval", "card": {
        "approval_id": 1, "kind": "clarification", "recipient": "info@providera.example", "quote_id": "A-v1",
        "valid": True, "body": "Hello,\n\nCould you confirm the cremation charge and whether an alternative container is acceptable?\n\nThank you."}}


def _steps(*pairs):
    return {"type": "next_steps", "items": [{"label": l, "action": {"do": d}} for l, d in pairs]}


def handle(text, files=None):
    t = (text or "").lower()
    if files or "quote" in t or "sample" in t:
        ev = [{"type": "text", "text": "[stub] I read the quote and found four lines. One charge is unresolved."},
              _quote(), _flags(), _plan(), _approval(), _steps(("Load sample quotes", "load_sample"))]
    elif "reply" in t or "v2" in t:
        ev = [{"type": "text", "text": "[stub] Provider A answered. Version 2 is saved; version 1 is kept."},
              {"type": "diff", "diff": [{"name": "Cremation", "v1": "Unresolved", "v2": "$1,450", "status": "resolved"}],
               "explanation": "The cremation fee is now quoted, so the unknown is resolved."},
              {"type": "memory", "query": "what did Provider A say about cremation", "answer": "Provider A had left the cremation fee open.",
               "nodes": ["Provider A", "Cremation fee"], "edges": [{"source": "Provider A", "relation": "left open", "target": "Cremation fee"}],
               "backend": "stub"}]
    else:
        ev = [{"type": "text", "text": "[stub] Tell me what she wanted, or drop in a quote."},
              _steps(("Load sample quotes", "load_sample"))]
    _LOG.append({"type": "user", "text": text})
    _LOG.extend(ev)
    return ev


def act(action):
    do = (action or {}).get("do")
    if do == "reset":
        _LOG.clear()
        return []
    if do == "approve":
        ev = [{"type": "receipt", "lines": ["[stub] Sent once to info@providera.example", "Sandbox outbox only."]},
              _steps(("Paste the reply", "reply"))]
    elif do == "rebuild":
        ev = [_approval()]
    elif do == "load_sample":
        return handle("sample quotes")
    else:
        ev = [{"type": "text", "text": f"[stub] action {do}"}]
    _LOG.extend(ev)
    return ev


def history():
    return list(_LOG)
