"""Last Wishes — Streamlit UI.

State is rebuilt from the database + Cognee on every run. st.session_state is not
used for data, so restarting Streamlit is the fresh-session test.
All side effects go through agent.py.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import streamlit as st

import agent
from agent import ApprovalBlocked, ModuleNotReady, fmt_money, item_amount_text

ARRANGEMENT_SENT = "Arrangement request sent — awaiting provider confirmation."

st.set_page_config(page_title="Last Wishes", page_icon="🕊️", layout="wide")

st.markdown("""
<style>
  .block-container {max-width: 1100px; padding-top: 2rem;}
  h1 {font-family: Georgia, 'Times New Roman', serif; font-weight: 600; letter-spacing: -0.5px;}
  h2, h3, h4 {font-family: Georgia, 'Times New Roman', serif; font-weight: 600;}
  .lw-hero {background: linear-gradient(135deg, rgba(196,154,108,0.18), rgba(120,140,170,0.12));
            border-radius: 18px; padding: 22px 26px; margin-bottom: 18px;}
  .lw-hero p {font-size: 1.05rem; line-height: 1.6; margin: 0.3rem 0;}
  .lw-step {border-left: 4px solid #c49a6c; background: rgba(196,154,108,0.10);
            border-radius: 10px; padding: 12px 16px; margin: 6px 0 16px; font-size: 0.98rem; line-height: 1.5;}
  .stTabs [data-baseweb="tab"] {font-size: 1rem; padding: 8px 14px;}
  .stButton button[kind="primary"] {border-radius: 999px; padding: 0.5rem 1.4rem;}
</style>
""", unsafe_allow_html=True)


def step_note(text: str) -> None:
    st.markdown(f'<div class="lw-step">{text}</div>', unsafe_allow_html=True)

try:
    agent.init()
except ModuleNotReady as e:
    st.error(f"Module not ready: `{e.module}`. The app needs the database module to show anything.")
    st.stop()


@contextmanager
def guard(what: str = ""):
    """Show a plain message instead of a traceback when a module isn't ready."""
    try:
        yield
    except ModuleNotReady as e:
        st.info(f"Module not ready: `{e.module}`. {what} will appear once it lands.")
    except ApprovalBlocked as e:
        st.warning(str(e))
    except ValueError as e:
        st.info(str(e))
    except Exception as e:  # keep the rest of the page usable
        st.error(f"{what or 'This step'} could not complete: {e}")


def money_cell(v):
    return "Unresolved" if v is None else fmt_money(v)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### Last Wishes")
    st.caption("The agent follows up. The family decides.")
    st.info("Providers are fictional. People are fictional.")
    with st.expander("Module status"):
        for name, status in agent.module_status().items():
            st.write(f"`{name}` — {status}")
    try:
        skips = agent.memory_skips()
        if skips:
            st.warning(f"{skips} memory write(s) were skipped because memory was not ready. "
                       "Reset and re-run once it is.")
    except Exception:
        pass
    st.divider()
    confirm = st.checkbox("I want to clear all demo data")
    if st.button("Reset demo data", disabled=not confirm):
        with guard("Reset"):
            agent.reset_demo()
            st.success("Demo data cleared.")
            st.rerun()

st.title("🕊️ Last Wishes")
st.markdown("""
<div class="lw-hero">
<p><b>When someone you love dies, you have a few days to plan a funeral, often while grieving.</b></p>
<p>Last Wishes remembers what they wanted, reads each funeral home's price list for you, points out anything
missing or questionable, and only sends a message when you say so.</p>
<p style="opacity:0.8">Work through the tabs left to right: <b>1 → 7</b>. The agent follows up. The family decides.</p>
</div>
""", unsafe_allow_html=True)

tabs = st.tabs(["1 · 💛 Her wishes", "2 · 📄 Price lists", "3 · ⚖️ Compare", "4 · ✉️ Send & approve",
                "5 · 📬 Replies", "6 · 🧠 What it remembers", "7 · 🔄 What changed"])

# ---------------------------------------------------------------------------
# Wishes
# ---------------------------------------------------------------------------

with tabs[0]:
    st.subheader("What Linda wanted")
    step_note("Start here. These are Linda's own words, recorded while she was alive, and confirmed by her daughter. "
              "Everything the agent does is checked against them.")
    with guard("Wishes"):
        ws = agent.wishes()
        if not ws:
            st.write("No wishes loaded yet. These come from the recorded note and the family's confirmation.")
            if st.button("💛 Load Linda's wishes"):
                agent.ingest_wishes()
                st.rerun()
        else:
            for w in ws:
                conf = f" · confirmed by {w['confirmed_by']}" if w.get("confirmed_by") else ""
                st.markdown(f"**{w['wish_id']}** — {w['text']}  \n"
                            f"<small>source {w.get('source_id')}{conf}</small>", unsafe_allow_html=True)
        with st.expander("Source documents"):
            for f in agent.WISH_FILES:
                p = agent.DATA_DIR / f
                if p.exists():
                    st.markdown(f"**{f}**")
                    st.text(p.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

with tabs[1]:
    st.subheader("Funeral home price lists")
    step_note("A <b>price list</b> (or quote) is what each funeral home sends: what they offer and what it costs. "
              "They all use different formats. Pick the ones to read and press the button. The agent pulls out every item and price.")
    candidates = sorted(p for p in agent.DATA_DIR.glob("*")
                        if p.suffix.lower() in (".txt", ".pdf") and p.name not in agent.WISH_FILES
                        and not p.name.startswith(("reply", "ftc")))
    picked = st.multiselect("Price lists to read", [p.name for p in candidates],
                            default=[p.name for p in candidates if p.name.startswith("quote_")])
    overrides = {}
    if picked:
        cols = st.columns(min(len(picked), 4))
        for i, name in enumerate(picked):
            with cols[i % len(cols)]:
                overrides[name] = st.text_input(f"Funeral home name for {name}",
                                                value=agent.provider_from_filename(name) or "",
                                                key=f"prov_{name}")
    up = st.file_uploader("Or upload your own price list (.txt or .pdf)", type=["txt", "pdf"])
    up_provider = st.text_input("Funeral home name for the uploaded file", value="", key="prov_upload") if up else ""
    if st.button("📄 Read these price lists", type="primary"):
        with guard("Reading quotes"):
            existing = agent.latest_quotes()
            jobs = [(agent.DATA_DIR / n, overrides.get(n)) for n in picked]
            if up is not None:
                agent.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                dest = agent.UPLOAD_DIR / Path(up.name).name
                dest.write_bytes(up.getvalue())
                jobs.append((dest, up_provider or agent.provider_from_filename(up.name)))
            for path, prov in jobs:
                prov = (prov or "").strip().upper()
                if not prov:
                    st.warning(f"Choose a provider letter for {path.name}.")
                    continue
                if prov in existing:
                    st.info(f"Provider {prov} already has {existing[prov]['quote_id']}; skipped.")
                    continue
                with st.spinner(f"Extracting {path.name}…"):
                    res = agent.ingest_document(path, prov)
                st.success(f"{path.name} → {res['quote_id']}: {len(res['items'])} line items.")
                for issue in res["issues"]:
                    st.caption(f"Needs review: {issue}")
            with st.spinner("Checking flags and building the plan…"):
                agent.run_analysis()
            st.rerun()

    with guard("Quotes"):
        qs = agent.quotes()
        if not qs:
            st.write("Nothing read yet. Press the button above.")
        for q in qs:
            sup = f" · supersedes {q['supersedes_id']}" if q.get("supersedes_id") else ""
            with st.expander(f"{q['quote_id']} — provider {q['provider']} (fictional), version {q['version']}{sup}"):
                items = agent.quote_items(q["quote_id"])
                st.dataframe([{"item": it["item_id"], "name": it.get("name"), "category": it.get("category"),
                               "price type": it.get("price_type"), "amount": item_amount_text(it),
                               "confidence": round(float(it.get("confidence") or 0), 2),
                               "excerpt": it.get("excerpt")} for it in items],
                             width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

with tabs[2]:
    st.subheader("Side by side")
    step_note("Here are the funeral homes next to each other. Prices that weren't listed show as <b>Unresolved</b>, never $0, "
              "so nobody looks cheaper by leaving things out. <b>Flags</b> are things worth asking about, and <b>Not needed</b> "
              "lists extras that go against Linda's wishes.")
    with guard("Comparison"):
        latest = agent.latest_quotes()
        if not latest:
            st.write("Read the price lists in tab 2 first.")
        else:
            if st.button("Re-run comparison"):
                agent.run_analysis()
                st.rerun()
            chosen = agent.chosen_plan()
            rows = []
            for prov, q in sorted(latest.items()):
                p = agent.plan_for_quote(q["quote_id"])
                if not p:
                    rows.append({"provider": f"{prov} (fictional)", "quote version": q["quote_id"],
                                 "known": "Plan not computed", "estimated range": "", "unresolved": "", "note": ""})
                    continue
                est_hi = p.get("estimated_high")
                est = (fmt_money(p.get("estimated_low") or 0, est_hi) if est_hi is not None
                       else f"from {fmt_money(p.get('estimated_low') or 0)} (open-ended)")
                unresolved = p.get("unresolved") or []
                note = ("Has unresolved charges — not ranked as lowest" if unresolved else
                        ("Lowest known total among complete quotes" if chosen and chosen["plan_id"] == p["plan_id"]
                         else ""))
                rows.append({"provider": f"{prov} (fictional)", "quote version": q["quote_id"],
                             "known": money_cell(p.get("known_total")), "estimated range": est,
                             "unresolved": ", ".join(unresolved) if unresolved else "None",
                             "note": note})
            st.dataframe(rows, width="stretch", hide_index=True)
            st.caption("Unresolved charges are shown as Unresolved, never as $0. Totals are for the services "
                       "that match the wishes.")

            st.markdown("#### 🚩 Worth asking about")
            all_flags = [f for q in latest.values() for f in agent.flags(q["quote_id"])]
            if not all_flags:
                st.write("No review flags.")
            for f in all_flags:
                st.markdown(f"**Review flag — needs clarification** · {f.get('quote_id')} · {f.get('kind')}")
                c1, c2 = st.columns(2)
                with c1:
                    st.caption("Provider statement")
                    st.info(f"“{f.get('excerpt', '')}”")
                with c2:
                    st.caption("Public FTC guidance")
                    st.success(f.get("reference") or "—")
                if f.get("message"):
                    st.write(f.get("message"))
                st.divider()

            st.markdown("#### ✂️ Extras she didn't want")
            items_by_id = {it["item_id"]: it for q in latest.values() for it in agent.quote_items(q["quote_id"])}
            nn_rows = []
            for prov, q in sorted(latest.items()):
                p = agent.plan_for_quote(q["quote_id"])
                for n in (p or {}).get("not_needed") or []:
                    it = items_by_id.get(n["item_id"], {})
                    nn_rows.append({"provider": prov, "item": it.get("name", n["item_id"]),
                                    "quoted": item_amount_text(it) if it else "",
                                    "savings if left out": money_cell(n.get("savings"))})
            if nn_rows:
                st.dataframe(nn_rows, width="stretch", hide_index=True)
            else:
                st.write("Nothing to leave out.")

            st.markdown("#### ✅ Plan that honors her wishes")
            if chosen:
                c_items = [items_by_id[i] for i in chosen.get("items") or [] if i in items_by_id]
                st.write(f"Based on **{chosen['quote_id']}** · known {money_cell(chosen.get('known_total'))}"
                         f" · honors {', '.join(chosen.get('wishes_satisfied') or []) or '—'}")
                if chosen.get("unresolved"):
                    st.warning("Unresolved in this plan: " + ", ".join(chosen["unresolved"]))
                st.dataframe([{"service": it.get("name"), "amount": item_amount_text(it),
                               "excerpt": it.get("excerpt")} for it in c_items],
                             width="stretch", hide_index=True)
            else:
                st.write("No current plan. Run the comparison after reading quotes.")

# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


def render_card(card: dict, persona_inquiry: str | None = None, persona_ok: bool = False):
    st.markdown(f"**To:** {card['recipient']}  \n**Quote version:** {card['quote_id']}  \n"
                f"**Approval:** {card['approval_id']}")
    st.text_area("Exact message", card["body"], height=220, disabled=True,
                 key=f"body_{card['approval_id']}")
    if card.get("sent"):
        if card["kind"] == "arrangement":
            st.success(ARRANGEMENT_SENT)
        else:
            st.success(f"{card['sent'].get('display_status') or 'Sent'} · sent once "
                       f"(outbox attempts: {card['sent'].get('attempts')})")
        return
    if card.get("outbox") and card["outbox"].get("status") == "failed":
        st.warning("The last send attempt failed. Sending again retries the same message; it will not duplicate.")
    if not card["valid"]:
        st.warning("This approval is invalidated: the quote changed after the card was prepared.")
        if st.button("Rebuild card for the current quote", key=f"rebuild_{card['approval_id']}"):
            with guard("Rebuilding"):
                agent.rebuild_card(card["approval_id"])
                st.rerun()
        return
    label = "Approve and send arrangement request" if card["kind"] == "arrangement" else "Approve and send"
    disabled = card["kind"] == "arrangement" and not persona_ok
    if st.button(label, key=f"send_{card['approval_id']}", type="primary", disabled=disabled):
        with guard("Sending"):
            agent.approve_and_send(card["approval_id"], persona_inquiry_id=persona_inquiry)
            st.rerun()


with tabs[3]:
    st.subheader("Messages to send")
    step_note("The agent drafts messages, but <b>nothing is sent until you approve it</b>. Each approval covers exactly one message. "
              "If a price changes, you'll be asked again. Step 1 asks a funeral home about something missing. "
              "Step 2 sends the family's final choice.")
    st.markdown("#### 1 · Ask about what's missing")
    with guard("Clarification"):
        latest = agent.latest_quotes()
        flagged = sorted({f["quote_id"].rsplit("-v", 1)[0] for q in latest.values() for f in agent.flags(q["quote_id"])
                          if f.get("kind") in ("unresolved_charge", "stated_requirement")})
        if flagged:
            c1, c2 = st.columns([1, 3])
            prov = c1.selectbox("Provider", flagged, key="clar_provider")
            if c2.button("Draft clarification"):
                with st.spinner("Drafting…"):
                    agent.prepare_clarification(prov)
                st.rerun()
        else:
            st.write("No open questions yet.")
        for card in reversed(agent.approval_cards("clarification")):
            with st.container(border=True):
                render_card(card)

    st.markdown("#### 2 · Send the family's choice")
    with guard("Arrangement"):
        latest = agent.latest_quotes()
        if not latest:
            st.write("Read quotes first.")
        else:
            sel = agent.current_selection()
            options = [q["quote_id"] for q in latest.values()]
            idx = options.index(sel["quote_id"]) if sel and sel.get("quote_id") in options else 0
            c1, c2 = st.columns([1, 3])
            choice = c1.selectbox("Provider and quote version", options, index=idx, key="sel_quote")
            if c2.button("Select this quote"):
                agent.select_quote(choice)
                st.rerun()
            if sel:
                st.write(f"Family's selection: **{sel['quote_id']}**"
                         + ("" if sel["quote_id"] in options else " (superseded — select again)"))

            st.markdown("**🪪 Quick identity check** (so nobody can send this on the family's behalf)")
            ps: dict = {}
            with guard("Identity check"):
                from persona import PERSONA_COPY  # noqa: E402

                st.caption(PERSONA_COPY)
                ps = agent.persona_state()
                b1, b2 = st.columns(2)
                if b1.button("Create verification inquiry"):
                    agent.create_persona_inquiry()
                    st.rerun()
                if ps.get("inquiry_id"):
                    if ps.get("hosted_url"):
                        st.link_button("Open Persona verification (sandbox)", ps["hosted_url"])
                    if b2.button("Check status"):
                        agent.check_persona_status(ps["inquiry_id"])
                        st.rerun()
                    st.write(f"Inquiry `{ps['inquiry_id']}` · status: **{ps.get('status') or 'not checked'}**"
                             + (" (sandbox-simulated)" if ps.get("sandbox_simulated") else ""))
                    with st.expander("Sandbox tools"):
                        if st.button("Simulate approval (sandbox only)"):
                            agent.simulate_persona_approval(ps["inquiry_id"])
                            st.rerun()
            persona_ok = ps.get("status") == "approved"

            if sel and sel["quote_id"] in options:
                prov = sel["quote_id"].rsplit("-v", 1)[0]
                if st.button("Prepare arrangement card"):
                    with guard("Arrangement card"):
                        agent.prepare_arrangement(prov)
                        st.rerun()
            for card in reversed(agent.approval_cards("arrangement")):
                with st.container(border=True):
                    ex = card.get("extra") or {}
                    st.markdown(f"**Provider {card['provider']} (fictional)**")
                    est_hi = ex.get("estimated_high")
                    cols = st.columns(3)
                    cols[0].metric("Known", money_cell(ex.get("known_total")))
                    cols[1].metric("Estimated", fmt_money(ex.get("estimated_low") or 0, est_hi)
                                   if est_hi is not None else f"from {fmt_money(ex.get('estimated_low') or 0)}")
                    cols[2].metric("Unresolved", ", ".join(ex.get("unresolved") or []) or "None")
                    if ex.get("services"):
                        st.dataframe([{"service": s_["name"], "amount": s_["amount"]} for s_ in ex["services"]],
                                     width="stretch", hide_index=True)
                    plan = agent.plan_for_quote_any(card["quote_id"])
                    if not persona_ok and not card.get("sent"):
                        st.caption("Sending is disabled until the identity check is approved.")
                    render_card(card, persona_inquiry=ps.get("inquiry_id"), persona_ok=persona_ok)
                    if plan:
                        st.markdown("**Evidence receipt**")
                        st.dataframe(agent.evidence_receipt(card["quote_id"], plan),
                                     width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

with tabs[4]:
    st.subheader("Replies from funeral homes")
    step_note("When a funeral home answers your question, drop their reply here. The agent reads it the same way it read the price lists, "
              "keeps the old version, and updates the plan.")
    with guard("Inbox"):
        latest = agent.latest_quotes()
        if not latest:
            st.write("Read quotes first.")
        else:
            replies = sorted(p.name for p in agent.DATA_DIR.glob("reply_*"))
            src = st.radio("Reply source", ["File in data/", "Upload", "Paste"], horizontal=True)
            text_or_path, fname, guess = None, None, None
            if src == "File in data/" and replies:
                fname = st.selectbox("Reply file", replies)
                text_or_path, guess = str(agent.DATA_DIR / fname), agent.provider_from_filename(fname)
            elif src == "Upload":
                f = st.file_uploader("Reply (.txt)", type=["txt"], key="reply_upload")
                if f:
                    text_or_path, fname = f.getvalue().decode("utf-8"), f.name
                    guess = agent.provider_from_filename(f.name)
            elif src == "Paste":
                text_or_path = st.text_area("Reply text", height=200) or None
            provs = sorted(latest)
            prov = st.selectbox("From provider", provs, index=provs.index(guess) if guess in provs else 0)
            if st.button("📬 Read this reply", type="primary", disabled=not text_or_path):
                with st.spinner("Reading the reply, recalling context, rebuilding the plan…"):
                    res = agent.ingest_reply(text_or_path, prov, filename=fname)
                st.success(f"Created {res['new_quote_id']} (kept {res['old_quote_id']}). See the Diff tab.")
            last = agent.latest_reply_diff()
            if last:
                st.write(f"Last reply: {last['filename']} → {last['new_quote_id']} "
                         f"(supersedes {last['old_quote_id']}).")

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def _label(n: dict) -> str:
    for k in ("name", "label", "text", "title", "id"):
        if n.get(k):
            return str(n[k])[:60]
    return json.dumps(n)[:60]


def render_graph(nodes: list[dict], edges: list[dict]):
    if not nodes and not edges:
        return
    lines = ["digraph G {", "rankdir=LR;", 'node [shape=box, style=rounded, fontsize=10];']
    for n in nodes:
        nid = str(n.get("id") or _label(n))
        lines.append(f'"{nid}" [label="{_label(n).replace(chr(34), "")}"];')
    for e in edges:
        s = str(e.get("source") or e.get("source_id") or e.get("from") or "")
        t = str(e.get("target") or e.get("target_id") or e.get("to") or "")
        rel = str(e.get("relationship") or e.get("relationship_name") or e.get("type") or e.get("label") or "")
        if s and t:
            lines.append(f'"{s}" -> "{t}" [label="{rel.replace(chr(34), "")}", fontsize=9];')
    lines.append("}")
    st.graphviz_chart("\n".join(lines))


with tabs[5]:
    st.subheader("What the agent remembers")
    step_note("Even after the app is closed and reopened, the agent remembers Linda's wishes, the questions it asked, and every version "
              "of each price list. Ask it anything below. You'll see exactly which memories it used.")
    with guard("Memory"):
        ws = agent.wishes()
        query = st.text_input("Ask the agent", value="What was pending, and what did she want?")
        cf = st.toggle("Counterfactual: recall without one wish")
        excl = []
        if cf:
            ids = [w["wish_id"] for w in ws] or ["W3"]
            excl = [st.selectbox("Leave out", ids, index=ids.index("W3") if "W3" in ids else 0)]
        if st.button("🧠 Remember", type="primary"):
            with st.spinner("Searching memory…"):
                agent.recall(query, exclude_wish_ids=excl)
            st.rerun()
        last = agent.last_recall()
        if last:
            res = last.get("result") or {}
            st.markdown(f"**Query:** `{last.get('query')}`"
                        + (f"  · left out: {', '.join(last['exclude_wish_ids'])}" if last.get("exclude_wish_ids") else ""))
            st.markdown("**Answer**")
            st.write(res.get("answer") or "—")
            nodes, edges = res.get("nodes") or [], res.get("edges") or []
            c1, c2 = st.columns(2)
            c1.markdown(f"**Nodes** ({len(nodes)})")
            c1.dataframe([{"label": _label(n), "type": n.get("type"), "via": n.get("via"), "id": n.get("id")}
                          for n in nodes], width="stretch", hide_index=True)
            c2.markdown(f"**Edges** ({len(edges)})")
            c2.dataframe([{"from": e.get("source_label") or e.get("source"), "relationship": e.get("relationship"),
                           "to": e.get("target_label") or e.get("target"), "text": e.get("text"),
                           "via": e.get("via")} for e in edges], width="stretch", hide_index=True)
            render_graph(nodes, edges)
            if res.get("meta"):
                with st.expander("Recall details"):
                    st.json(res["meta"])
        with st.expander("Whole memory graph"):
            if st.button("Load graph snapshot"):
                snap = agent.graph_snapshot()
                st.caption(f"{len(snap.get('nodes') or [])} nodes · {len(snap.get('edges') or [])} edges")
                render_graph(snap.get("nodes") or [], snap.get("edges") or [])

# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

with tabs[6]:
    st.subheader("What changed after the family asked")
    step_note("The old price list is kept, the new one sits next to it, and the agent explains in plain words what changed and why it matters.")
    with guard("Diff"):
        d = agent.latest_reply_diff()
        if not d:
            st.write("No reply yet. Add one in tab 5.")
        else:
            diff = d.get("diff") or {}
            st.write(f"**{d['old_quote_id']}** (kept) → **{d['new_quote_id']}** from {d.get('filename')}")
            st.info(d.get("explanation") or "")
            st.dataframe([{"line": r["name"], d["old_quote_id"]: r["v1"], d["new_quote_id"]: r["v2"],
                           "status": r["status"], "reply excerpt": r.get("v2_excerpt", "")}
                          for r in diff.get("lines") or []], width="stretch", hide_index=True)
            op, np_ = diff.get("old_plan"), diff.get("new_plan")
            c1, c2 = st.columns(2)
            for col, title, p in ((c1, "Plan before the reply", op), (c2, "Plan after the reply", np_)):
                with col:
                    st.markdown(f"**{title}**")
                    if not p:
                        st.write("—")
                        continue
                    est_hi = p.get("estimated_high")
                    st.write(f"Quote {p.get('quote_id')} · known {money_cell(p.get('known_total'))} · estimated "
                             + (fmt_money(p.get('estimated_low') or 0, est_hi) if est_hi is not None
                                else f"from {fmt_money(p.get('estimated_low') or 0)}"))
                    st.write("Unresolved: " + (", ".join(p.get("unresolved") or []) or "None"))
            rec = d.get("recall") or {}
            if rec.get("query"):
                with st.expander("Memory recall used for this explanation"):
                    st.markdown(f"**Query:** `{rec['query']}`")
                    st.write(rec.get("answer") or "—")

# ---------------------------------------------------------------------------
# Trace drawer
# ---------------------------------------------------------------------------

with st.expander("Trace — Superlinked SIE calls"):
    with guard("Trace"):
        calls = agent.sie_calls()
        if not calls:
            st.write("No SIE calls logged yet.")
        else:
            rows = []
            for c in calls:
                out = agent._jsonish(c.get("output_json"))
                excerpt = ""
                if isinstance(out, dict):
                    ex = out.get("excerpts") or out.get("excerpt") or ""
                    excerpt = " | ".join(ex) if isinstance(ex, list) else str(ex)
                elif out:
                    excerpt = str(out)
                rows.append({"time": str(c.get("ts", "")), "recipe": c.get("recipe"), "model": c.get("model"),
                             "latency ms": c.get("latency_ms"), "input chars": c.get("input_chars"),
                             "excerpt": excerpt[:300]})
            st.dataframe(rows, width="stretch", hide_index=True)
