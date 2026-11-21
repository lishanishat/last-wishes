"""Event constructors. Every event is a plain JSON-serializable dict with a 'type' key.

Types: text, quote, flags, plan, approval, diff, memory, next_steps, receipt, error
(plus 'user' for the user's own messages in history()).
"""
from __future__ import annotations

import json
from typing import Any

TYPES = ("text", "quote", "flags", "plan", "approval", "diff", "memory", "next_steps", "receipt", "error", "user")


def jsonable(obj: Any) -> Any:
    """Round-trip through JSON so every event is safe to store and send (datetimes -> str)."""
    return json.loads(json.dumps(obj, default=str, ensure_ascii=False))


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def user(t: str, files: list[str] | None = None, action: dict | None = None) -> dict:
    ev: dict = {"type": "user", "text": t}
    if files:
        ev["files"] = list(files)
    if action:
        ev["action"] = jsonable(action)
    return ev


def error(message: str) -> dict:
    return {"type": "error", "message": message}


def quote(provider, quote_id, version, fictional, source, rows, known_total, estimated_low, estimated_high,
          unresolved) -> dict:
    return jsonable({"type": "quote", "provider": provider, "quote_id": quote_id, "version": version,
                     "fictional": fictional, "source": source, "rows": rows, "known_total": known_total,
                     "estimated_low": estimated_low, "estimated_high": estimated_high,
                     "unresolved": unresolved})


def flags(items: list[dict]) -> dict:
    return jsonable({"type": "flags", "flags": items})


def plan(p: dict, note: str = "") -> dict:
    return jsonable({"type": "plan", "plan": p, "note": note})


def approval(card: dict) -> dict:
    return jsonable({"type": "approval", "card": card})


def diff(rows: list[dict], explanation: str) -> dict:
    return jsonable({"type": "diff", "diff": rows, "explanation": explanation})


def memory(query, answer, nodes, edges, backend) -> dict:
    return jsonable({"type": "memory", "query": query, "answer": answer, "nodes": nodes, "edges": edges,
                     "backend": backend})


def next_steps(items: list[dict]) -> dict:
    return jsonable({"type": "next_steps", "items": items})


def receipt(lines: list[str], rows: list[dict] | None = None) -> dict:
    ev: dict = {"type": "receipt", "lines": lines}
    if rows:
        ev["rows"] = rows
    return jsonable(ev)
