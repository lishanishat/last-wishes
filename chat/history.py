"""Chat history persisted as audit_log rows (action 'chat_message'). No new tables.

Each row: {"seq": ns timestamp, "role": "user"|"agent", "events": [event, ...]}.
history() returns the flat, ordered list of event dicts (user messages are {"type": "user"} events).
"""
from __future__ import annotations

import time

import agent

ACTION = "chat_message"
ACTOR = "chat"


def record(role: str, events: list[dict]) -> None:
    agent.audit(ACTION, {"seq": time.time_ns(), "role": role, "events": events}, actor=ACTOR)


def load() -> list[dict]:
    rows = []
    for r in agent.audit_events(ACTION):
        d = r.get("detail")
        if isinstance(d, dict) and isinstance(d.get("events"), list):
            rows.append(d)
    rows.sort(key=lambda d: d.get("seq", 0))
    out: list[dict] = []
    for d in rows:
        out.extend(e for e in d["events"] if isinstance(e, dict))
    return out
