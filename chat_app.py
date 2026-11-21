"""Last Wishes, chat-first shell. `streamlit run chat_app.py`

Only renders events from chat.engine. The engine/DB is the state of truth;
st.session_state is a render cache rebuilt from engine.history() on load.
"""
from __future__ import annotations

import os

import streamlit as st

st.set_page_config(page_title="Last Wishes", layout="centered")

from chat import render, style  # noqa: E402

STUB = False
if os.environ.get("LW_CHAT_STUB") == "1":
    from chat import _stub_engine as engine  # noqa: E402
    STUB = True
else:
    try:
        from chat import engine  # noqa: E402
    except Exception:
        from chat import _stub_engine as engine  # noqa: E402
        STUB = True

import agent  # noqa: E402

st.markdown(style.CSS, unsafe_allow_html=True)

WELCOME = ("I help compare funeral quotes against what she wanted. Share her wishes, or drop in a quote or a "
           "provider reply. I will say what I found and what the next step is. Nothing is sent until you approve it.")


def _init_agent() -> None:
    try:
        agent.init()
    except Exception as e:  # keep the shell usable if a module is missing
        st.warning(f"Storage is not ready: {e}")


def _load_history() -> list[dict]:
    try:
        return [e for e in engine.history() if isinstance(e, dict)]
    except Exception as e:
        st.error(f"Could not restore the conversation: {e}")
        return []


_init_agent()
if "log" not in st.session_state:
    st.session_state.log = _load_history()


def _run(fn, *args, **kw) -> None:
    """Call the engine, cache the returned events for rendering."""
    try:
        with st.spinner("Working on it. Reading documents can take a minute."):
            events = fn(*args, **kw) or []
    except Exception as e:
        events = [{"type": "error", "message": f"That did not work: {e}"}]
    try:
        st.session_state.log = _load_history()  # engine/DB is the state of truth
    except Exception:
        st.session_state.log.extend(events)
    if not st.session_state.log:
        st.session_state.log = list(events)
    elif events and events[-1].get("type") == "error" and events[-1] not in st.session_state.log:
        st.session_state.log.append(events[-1])
    st.rerun()


def act(action: dict) -> None:
    _run(engine.act, action)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### Last Wishes")
    st.caption("The agent follows up. The family decides.")
    if STUB:
        st.markdown(render._badge("stub engine", "lw-stub"), unsafe_allow_html=True)
    st.caption("Providers and people are fictional.")

    st.markdown("#### What she wanted")
    try:
        ws = agent.wishes()
    except Exception:
        ws = []
    if not ws:
        st.caption("No wishes loaded yet.")
    for w in ws:
        src = f" (source {w.get('source_id')})" if w.get("source_id") else ""
        st.markdown(f"- {w.get('text', '')}{src}")

    with st.expander("Memory"):
        try:
            last = agent.last_recall()
        except Exception:
            last = None
        r = (last or {}).get("result", last) if last else None
        if not r:
            st.caption("Nothing recalled yet.")
        else:
            st.caption(f"Query: {r.get('query', '')}")
            if r.get("answer"):
                st.markdown(str(r["answer"]))
            render.memory_lists(st, r.get("nodes") or [], r.get("edges") or [])

    with st.expander("Trace"):
        try:
            calls = agent.sie_calls()
        except Exception:
            calls = []
        if not calls:
            st.caption("No model calls yet.")
        else:
            st.dataframe([{"recipe": c.get("recipe"), "model": c.get("model"),
                           "latency_ms": c.get("latency_ms"), "backend": c.get("backend")} for c in calls],
                         hide_index=True, width="stretch")

    st.divider()
    with st.expander("Start over"):
        st.caption("This clears the conversation and all saved quotes, approvals and memory for this demo.")
        sure = st.checkbox("Yes, clear everything", key="sure_reset")
        if st.button("Start over", disabled=not sure):
            try:
                engine.act({"do": "reset"})
            except Exception as e:
                st.error(f"Could not reset: {e}")
            else:
                st.session_state.clear()
                st.rerun()

# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

st.markdown("## Last Wishes")

log = st.session_state.log
last_next = max((i for i, e in enumerate(log) if e.get("type") == "next_steps"), default=-1)
last_user = max((i for i, e in enumerate(log) if render.is_user_event(e)), default=-1)
receipt_idx = [i for i, e in enumerate(log) if e.get("type") == "receipt"]

if not log:
    with st.chat_message("assistant"):
        st.markdown(WELCOME)
        if st.button("Load sample quotes (fictional)", key="sample"):
            _run(engine.act, {"do": "load_sample"})

# Group consecutive non-user events under one assistant bubble.
i = 0
while i < len(log):
    ev = log[i]
    if render.is_user_event(ev):
        with st.chat_message("user"):
            st.markdown(ev.get("text", ""))
        i += 1
        continue
    with st.chat_message("assistant"):
        while i < len(log) and not render.is_user_event(log[i]):
            e = log[i]
            render.render_event(e, act, key=f"e{i}", latest=(i == last_next),
                                answered=any(r > i for r in receipt_idx))
            i += 1

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

try:
    value = st.chat_input("Paste wishes, a quote, or a provider reply", accept_file="multiple",
                          file_type=["txt", "pdf"])
    side_upload = None
except TypeError:
    value = st.chat_input("Paste wishes, a quote, or a provider reply")
    side_upload = st.sidebar.file_uploader("Upload a document", type=["txt", "pdf"], accept_multiple_files=True)

if value:
    if isinstance(value, str):
        text, files = value, list(side_upload or [])
    else:
        text, files = value.text or "", list(value.files or [])
    packed = [{"name": f.name, "bytes": f.getvalue()} for f in files] or None
    _run(engine.handle, text, files=packed)
