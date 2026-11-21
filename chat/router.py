"""Rule-based intent routing for free chat text. No LLM, no provider-specific logic.

route(text) -> {"intent": ..., "provider": str|None, "body": str, "urls": [..]}
intents: wishes | quote | reply | compare | recall | url | reset_hint | approve_hint | help
"""
from __future__ import annotations

import re

URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
_PREFIX = re.compile(
    r"^\s*(?P<kind>reply|quote|wishes?|price\s*list)\s*(?:from|for|of)?\s*(?:provider\s+)?"
    r"(?P<prov>[A-Za-z0-9]{1,3})?\s*[:\-]\s*(?P<body>.*)$", re.I | re.S)
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
_RECALL = re.compile(
    r"what\s+(?:was|is|were)\s+(?:still\s+)?(?:pending|open|outstanding|unresolved)|"
    r"what\s+did\s+\w+\s+(?:want|wish|ask|say|decide)|what\s+(?:do|did)\s+we\s+(?:know|remember)|"
    r"remind\s+me|\brecall\b|what\s+were\s+(?:her|his|their|the)\s+wishes", re.I)
_COMPARE = re.compile(r"^\s*(?:please\s+)?(?:compare|run\s+(?:the\s+)?comparison|which\s+(?:one|quote|provider)|"
                      r"show\s+(?:me\s+)?(?:the\s+)?(?:comparison|plan|options))\b", re.I)
_APPROVE = re.compile(r"^\s*(?:ok(?:ay)?[,. ]*)?(?:approve|send\s+it|go\s+ahead|yes[, ]*send)\b", re.I)
_RESET = re.compile(r"^\s*(?:reset|start\s+over|clear\s+everything)\b", re.I)
_WISH_WORDS = re.compile(r"\b(?:wish(?:es)?|want(?:s|ed)?|would\s+like|i'?d\s+like|don'?t\s+want|do\s+not\s+want|"
                         r"no\s+(?:viewing|funeral|service)|cremat\w+|burial|budget|avoid|simple|unnecessary)\b", re.I)
_PROVIDER_MENTION = re.compile(r"^\W*(?:quote|statement|estimate|price list)?.*?\bprovider\s+([A-Za-z0-9]{1,3})\b", re.I)


def is_email_like(text: str) -> bool:
    """A pasted provider email: a From:/Subject: header block or 'Re:' subject."""
    head = text[:1200]
    has_from = re.search(r"^\s*From:\s*.+", head, re.M | re.I)
    has_subj = re.search(r"^\s*Subject:\s*.+", head, re.M | re.I)
    has_re = re.search(r"^\s*Subject:\s*(?:re|fw|fwd):", head, re.M | re.I)
    return bool((has_from and has_subj) or has_re)


def sender_email(text: str) -> str | None:
    m = re.search(r"^\s*From:.*?([\w.+-]+@[\w-]+(?:\.[\w-]+)+)", text, re.M | re.I)
    return m.group(1) if m else None


def money_count(text: str) -> int:
    return len(_MONEY.findall(text))


def route(text: str) -> dict:
    raw = text or ""
    t = raw.strip()
    urls = URL_RE.findall(t)
    out = {"intent": "help", "provider": None, "body": t, "urls": urls}
    if not t:
        return out
    m = _PREFIX.match(t)
    if m and m.group("body").strip():
        kind = m.group("kind").lower()
        prov = (m.group("prov") or "").upper() or None
        out["body"] = m.group("body").strip()
        out["provider"] = prov
        out["intent"] = "reply" if kind == "reply" else "wishes" if kind.startswith("wish") else "quote"
        return out
    if urls and len(URL_RE.sub("", t).strip()) < 25:
        out["intent"] = "url"
        return out
    if _RESET.match(t) and len(t) < 40:
        out["intent"] = "reset_hint"
        return out
    if _APPROVE.match(t) and len(t) < 60:
        out["intent"] = "approve_hint"
        return out
    if _COMPARE.match(t) and len(t) < 120:
        out["intent"] = "compare"
        return out
    if _RECALL.search(t) and len(t) < 240:
        out["intent"] = "recall"
        return out
    if is_email_like(t):
        out["intent"] = "reply"
        return out
    if money_count(t) >= 2:
        pm = _PROVIDER_MENTION.search(t[:300])
        out["intent"] = "quote"
        out["provider"] = pm.group(1).upper() if pm else None
        return out
    if _WISH_WORDS.search(t) and len(t) > 25:
        out["intent"] = "wishes"
        return out
    return out
