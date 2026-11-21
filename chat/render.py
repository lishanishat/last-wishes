"""Rendering of chat.engine events.

Top half: pure helpers (no Streamlit) so they can be unit tested.
Bottom half: render_event(), which draws one event with Streamlit.
"""
from __future__ import annotations

import html
from typing import Any, Optional

BANNED_WORDS = ("illegal", "violation", "violate")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def money(v: Optional[float]) -> str:
    """Unknown is never $0."""
    if v is None:
        return "Unresolved"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "Unresolved"
    if abs(f - round(f)) < 0.005:
        return f"${round(f):,}"
    return f"${f:,.2f}"


def range_text(low: Optional[float], high: Optional[float]) -> str:
    """Estimated range; an open upper end is stated, never invented."""
    if low is None and high is None:
        return "Unresolved"
    if high is None:
        return f"from {money(low or 0)} (no ceiling quoted)"
    if low is None or abs(float(high) - float(low)) < 0.005:
        return money(high)
    return f"{money(low)} to {money(high)}"


def totals_line(known: Any, low: Any, high: Any, unresolved: Any) -> dict:
    """Three labelled parts for the Known / Estimated / Unresolved line."""
    unres = list(unresolved or [])
    return {
        "known": money(known),
        "estimated": range_text(low, high),
        "unresolved": ", ".join(str(u) for u in unres) if unres else "None",
        "has_unresolved": bool(unres),
    }


def quote_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows or []:
        out.append({
            "Item": r.get("name") or "",
            "Category": (r.get("category") or "").replace("_", " "),
            "Price type": (r.get("price_type") or "").replace("_", " "),
            "Amount": r.get("amount_text") or "Unresolved",
        })
    return out


def split_rows(rows: list[dict], limit: int = 12, head: int = 8) -> tuple[list[dict], list[dict]]:
    """Long tables (a real price list can have 100 lines) show the first few, the rest folded away."""
    if len(rows) <= limit:
        return rows, []
    return rows[:head], rows[head:]


def soften(text: Any) -> str:
    """Safety net: the shell never shows accusatory wording even if upstream slips."""
    s = str(text or "")
    for w, repl in (("illegal", "needs clarification"), ("violation", "needs clarification"),
                    ("violate", "conflict with")):
        s = s.replace(w, repl).replace(w.capitalize(), repl.capitalize())
    return s


def flag_columns(flag: dict) -> dict:
    """Left: provider excerpt. Right: FTC reference. Below: message."""
    return {
        "title": f"Needs clarification: {flag.get('quote_id', '')}".strip(),
        "provider": soften(flag.get("excerpt")),
        "reference": soften(flag.get("reference")) or "No reference attached.",
        "message": soften(flag.get("message")),
        "kind": (flag.get("kind") or "").replace("_", " "),
    }


def not_needed_rows(plan: dict) -> list[dict]:
    rows = []
    for n in (plan or {}).get("not_needed") or []:
        if isinstance(n, dict):
            name = n.get("name") or n.get("item") or n.get("item_id") or ""
            sav = n.get("savings")
        else:
            name, sav = str(n), None
        rows.append({"Item": name, "Savings if left out": money(sav) if sav is not None else "Not quoted"})
    return rows


def total_savings(plan: dict) -> Optional[float]:
    vals = [n.get("savings") for n in (plan or {}).get("not_needed") or []
            if isinstance(n, dict) and n.get("savings") is not None]
    return float(sum(vals)) if vals else None


def chip_action(item: dict) -> dict:
    """The dict passed to engine.act() for a next-step chip (copied, never mutated)."""
    a = item.get("action")
    if isinstance(a, dict):
        return dict(a)
    return {"do": str(a or "")}


def chip_key(prefix: str, idx: int, item: dict) -> str:
    return f"{prefix}_chip_{idx}_{chip_action(item).get('do', '')}"


def approve_action(card: dict) -> dict:
    return {"do": "approve", "approval_id": card.get("approval_id")}


def rebuild_action(card: dict) -> dict:
    return {"do": "rebuild", "approval_id": card.get("approval_id")}


def card_is_stale(card: dict) -> bool:
    return card.get("valid") is False or bool(card.get("stale"))


def card_is_sent(card: dict) -> bool:
    return bool(card.get("sent"))


def diff_rows(diff: Any) -> list[dict]:
    rows = diff.get("rows") if isinstance(diff, dict) else diff
    out = []
    for r in rows or []:
        out.append({
            "Line": r.get("name") or "",
            "Before": r.get("v1") if r.get("v1") is not None else "",
            "After": r.get("v2") if r.get("v2") is not None else "",
            "Change": r.get("status") or "",
        })
    return out


def is_user_event(ev: dict) -> bool:
    return ev.get("role") == "user" or ev.get("type") in ("user", "user_text", "user_message")


def table_html(rows: list[dict], right_cols: tuple[str, ...] = ("Amount",)) -> str:
    """Small escaped HTML table that wraps text instead of scrolling the page."""
    if not rows:
        return ""
    cols = list(rows[0].keys())
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = ""
    for r in rows:
        tds = "".join(
            f"<td class=\"{'amt' if c in right_cols else ''}\">{html.escape(str(r.get(c, '')))}</td>" for c in cols)
        body += f"<tr>{tds}</tr>"
    return f"<div class=\"lw-table-wrap\"><table class=\"lw\"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


# ---------------------------------------------------------------------------
# Streamlit rendering
# ---------------------------------------------------------------------------


def render_event(ev: dict, act, key: str, *, latest: bool = True, answered: bool = False) -> None:
    """Draw one event. `act(action_dict)` is called when a button is pressed.

    latest: this is the newest event group (chips only live there).
    answered: a later receipt exists, so the approval button is hidden.
    """
    import streamlit as st

    t = ev.get("type")
    if t == "text":
        st.markdown(ev.get("text", ""))
    elif t == "quote":
        _quote(st, ev)
    elif t == "flags":
        _flags(st, ev)
    elif t == "plan":
        _plan(st, ev)
    elif t == "approval":
        _approval(st, ev.get("card") or {}, act, key, answered)
    elif t == "diff":
        st.markdown("**What changed**")
        st.markdown(table_html(diff_rows(ev.get("diff")), right_cols=("Before", "After")), unsafe_allow_html=True)
        if ev.get("explanation"):
            st.markdown(ev["explanation"])
    elif t == "memory":
        _memory(st, ev)
    elif t == "next_steps":
        if latest:
            _chips(st, ev.get("items") or [], act, key)
    elif t == "receipt":
        for line in ev.get("lines") or []:
            st.markdown(f"- {line}")
    elif t == "error":
        st.error(ev.get("message") or "Something went wrong.")
    else:
        st.caption(f"Unrecognized event type: {t}")


def _badge(text: str, cls: str = "") -> str:
    return f"<span class=\"lw-badge {cls}\">{html.escape(text)}</span>"


def _quote(st, ev: dict) -> None:
    head = f"**Provider {ev.get('provider', '')}, version {ev.get('version', '')}** ({ev.get('quote_id', '')})"
    if ev.get("fictional"):
        head += _badge("FICTIONAL")
    st.markdown(head, unsafe_allow_html=True)
    if ev.get("source"):
        st.caption(f"Source: {ev['source']}")
    rows = quote_rows(ev.get("rows"))
    head_rows, rest = split_rows(rows)
    st.markdown(table_html(head_rows), unsafe_allow_html=True)
    if rest:
        with st.expander(f"Show the other {len(rest)} lines"):
            st.markdown(table_html(rest), unsafe_allow_html=True)
    tl = totals_line(ev.get("known_total"), ev.get("estimated_low"), ev.get("estimated_high"), ev.get("unresolved"))
    _totals(st, tl)


def _totals(st, tl: dict) -> None:
    st.markdown(
        f"<div class=\"lw-totals\"><b>Known:</b> {html.escape(tl['known'])} &nbsp;·&nbsp; "
        f"<b>Estimated:</b> {html.escape(tl['estimated'])} &nbsp;·&nbsp; "
        f"<b>Unresolved:</b> {html.escape(tl['unresolved'])}</div>", unsafe_allow_html=True)


def _flags(st, ev: dict) -> None:
    flags = ev.get("flags") or []
    if not flags:
        st.markdown("No review flags on this quote.")
        return
    for i, f in enumerate(flags):
        c = flag_columns(f)
        st.markdown(f"**{html.escape(c['title'])}**", unsafe_allow_html=True)
        st.markdown(
            "<div class=\"lw-flag-cols\"><div><div class=\"lw-label\">Provider wrote</div>"
            f"<blockquote class=\"lw-quote\">{html.escape(c['provider'])}</blockquote></div>"
            "<div><div class=\"lw-label\">Public FTC guidance</div>"
            f"<blockquote class=\"lw-ref\">{html.escape(c['reference'])}</blockquote></div></div>",
            unsafe_allow_html=True)
        if c["message"]:
            st.markdown(c["message"])


def _plan(st, ev: dict) -> None:
    p = ev.get("plan") or {}
    st.markdown("**Suggested plan**" + (f" based on {p['quote_id']}" if p.get("quote_id") else ""))
    _totals(st, totals_line(p.get("known_total"), p.get("estimated_low"), p.get("estimated_high"),
                            p.get("unresolved")))
    nn = not_needed_rows(p)
    if nn:
        sav = total_savings(p)
        st.markdown("**Not needed**" + (f" (quoted savings {money(sav)})" if sav is not None else ""))
        st.markdown(table_html(nn, right_cols=("Savings if left out",)), unsafe_allow_html=True)
    if ev.get("note"):
        st.markdown(soften(ev["note"]))


def _approval(st, card: dict, act, key: str, answered: bool) -> None:
    with st.container(border=True):
        st.markdown(f"**To:** {card.get('recipient', '')}  \n**Quote version:** {card.get('quote_id', '')}")
        st.markdown("<div class=\"lw-label\">Exact message</div>"
                    f"<div class=\"lw-msg\">{html.escape(str(card.get('body', ''))).replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
        if card_is_sent(card) or answered:
            st.caption("Sent." if card_is_sent(card) else "Already handled below.")
            return
        if card_is_stale(card):
            st.warning("The quote changed after this card was prepared, so the approval no longer applies.")
            if st.button("Rebuild", key=f"{key}_rebuild"):
                act(rebuild_action(card))
            return
        if st.button("Approve and send", key=f"{key}_approve", type="primary"):
            act(approve_action(card))


def _memory(st, ev: dict) -> None:
    st.markdown("**What the agent remembered**")
    if ev.get("query"):
        st.caption(f"Recall query: {ev['query']}")
    if ev.get("answer"):
        st.markdown(ev["answer"])
    nodes, edges = ev.get("nodes") or [], ev.get("edges") or []
    if nodes or edges:
        with st.expander(f"{len(nodes)} nodes, {len(edges)} edges" + (f" ({ev['backend']})" if ev.get("backend") else "")):
            memory_lists(st, nodes, edges)


def memory_lists(st, nodes: list, edges: list) -> None:
    for n in nodes:
        st.markdown(f"- {_node_text(n)}")
    if edges:
        st.caption("Edges")
        for e in edges:
            st.markdown(f"- {_edge_text(e)}")


def _node_text(n: Any) -> str:
    if isinstance(n, dict):
        return str(n.get("label") or n.get("name") or n.get("id") or n)
    return str(n)


def _edge_text(e: Any) -> str:
    if isinstance(e, dict):
        a = e.get("source") or e.get("from") or e.get("src") or ""
        b = e.get("target") or e.get("to") or e.get("dst") or ""
        r = e.get("relation") or e.get("label") or e.get("type") or "to"
        return f"{a} {r} {b}".strip()
    return str(e)


def _chips(st, items: list[dict], act, key: str) -> None:
    if not items:
        return
    st.caption("Next steps")
    cols = st.columns(min(len(items), 3))
    for i, it in enumerate(items):
        with cols[i % len(cols)]:
            if st.button(it.get("label", "Continue"), key=chip_key(key, i, it)):
                act(chip_action(it))
