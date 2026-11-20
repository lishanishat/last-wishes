# Lisha — Role & Checkpoints

**You own:** the repo and GitHub, the app shell and UI, **SingleStore** (canonical state), approvals + outbox (send once), **Persona**, integration, README, demo video, submission.

**Manank owns:** seed data, **Superlinked SIE** pipeline, rules/flags, optimizer, **Cognee** memory, benchmark, **Firedrill**. See [MANANK.md](MANANK.md). Full spec: [LAST_WISHES.md](LAST_WISHES.md).

**Stack:** Python 3.11 · Streamlit (UI) · `singlestoredb` · `requests` (Persona, SIE if no SDK) · one LLM key for drafting text.

**Shared rule:** don't change the data contracts in LAST_WISHES.md §9 without telling Manank.

---

## Repo layout (you create it)

```
last-wishes/
  app.py               # Streamlit UI (you)
  agent.py             # orchestrator: calls pipeline + memory, writes DB (you)
  db.py                # SingleStore connection + schema + queries (you)
  approvals.py         # approval cards, payload hash, invalidation (you)
  outbox.py            # idempotent send (you)
  persona.py           # Persona sandbox inquiry + status check (you)
  pipeline/            # (Manank) extract.py, classify.py, flags.py, optimizer.py, sie_client.py
  memory/              # (Manank) cognee_mem.py
  data/                # (Manank) quotes, wishes, reply, real price list, ftc_reference.txt
  tests/firedrill/     # (Manank) scenarios
  bench/               # (Manank) benchmark script + results.md
  .env.example  requirements.txt  README.md
```

---

## Tasks by checkpoint

### CP0 — by 2:20 — Setup
- [ ] Create GitHub repo `last-wishes`, push the skeleton above (empty files + `requirements.txt` + `.env.example`).
- [ ] Add Manank as a collaborator. He doesn't have `gh`; plain `git` over HTTPS with a token or GitHub Desktop works. **Fallback:** he sends you files and you commit them.
- [ ] Branches: `main` (always runs), you work on `ui`, Manank on `pipeline`. You do all merges into `main`.
- [ ] SingleStore: create a free workspace, get the connection string into `.env`, confirm `SELECT 1` works.
- [ ] Persona: sandbox account, API key, create an inquiry template (government ID or selfie, sandbox).
- [ ] Paste LAST_WISHES.md into the repo as `SPEC.md`.

### CP1 — by 2:45 — Data in
- [ ] `db.py`: create every table in LAST_WISHES.md §10 (add the vector columns only if quick, otherwise later).
- [ ] `agent.py`: `ingest_document(path)` → calls Manank's `extract_quote()` + `classify()` → writes `quotes` + `line_items` → logs each SIE call to `sie_calls`.
- [ ] `app.py` tabs: **Wishes** (shows wishes from DB + Cognee), **Quotes** (upload or select docs, then "Read quotes"), **Compare** (table per provider: known / estimated / unresolved).
- [ ] Merge Manank's `pipeline` branch once `extract_quote()` returns real LineItems.
- ✅ **Check:** pressing "Read quotes" on A, B, C + the real list fills the Compare table from the DB, with no hardcoded numbers.

### CP2 — by 3:10 — Loop 1
- [ ] Compare tab shows **flags** (excerpt beside reference), **"Not needed"** column, and the optimizer plan (from Manank).
- [ ] `approvals.py`: approval card = recipient + exact message + quote version; store `payload_hash`. Approve → status `approved`.
- [ ] `outbox.py`: `send(approval_id)` with `idempotency_key = hash(approval_id + payload_hash)` and a UNIQUE constraint, so a retry can never send twice. Sandbox outbox table; optional SMTP to Manank's inbox only if it takes under 10 min.
- [ ] Clarification draft comes from the LLM using only validated data (Manank gives you `draft_clarification(flags, plan)` or you write a 10-line prompt).
- [ ] **Inbox** tab: upload or paste a provider reply → `agent.ingest_reply()` → Manank's extract → new `quotes` row with `version=2, supersedes_id=v1` → plan marked `stale`.
- ✅ **Check:** approve → exactly one outbox row; upload reply → Quote v2 exists, v1 still exists.

### CP3 — by 3:30 — Memory + action
- [ ] **Fresh session:** app start reads only DB + Cognee (no `st.session_state` carried over). Test it by actually restarting Streamlit.
- [ ] **Memory panel:** shows Manank's `recall()` output: the query, the returned nodes and edges, and the answer text.
- [ ] **Diff view:** v1 vs v2 line by line, plus old plan vs replanned plan, plus the "what changed and why" text.
- [ ] `persona.py`: create an inquiry → open the hosted link → poll status; Approval #2 is blocked until `approved`; store `persona_inquiry_id` on the approval.
- [ ] **Approval #2 card:** provider + recipient, quote version, services, known/estimated/unresolved totals, exact message → "Approve and send arrangement request" → status text "Arrangement request sent — awaiting provider confirmation."
- [ ] **Invalidation:** if the latest quote version ≠ the card's quote version, the card is invalid and gets rebuilt.
- [ ] **Evidence receipt:** each line links to its wish, excerpt and quote version.
- ✅ **Check:** full run end to end after a restart, with no manual DB edits.

### CP4 — by 3:45 — Freeze
- [ ] **Trace drawer** (`st.expander`): rows from `sie_calls` (recipe, model, latency, excerpt).
- [ ] Show Manank's `bench/results.md` and Firedrill results in the UI or README.
- [ ] Rehearse the full demo twice (§15 of the spec). Fix only blockers, no new features.

### CP5 — by 4:00 — Submitted
- [ ] Record the demo video (≤ 3 min, screen recording, voiceover). Restart the app on camera for the fresh-session moment.
- [ ] README: setup, `.env.example`, architecture diagram, every SIE recipe and Cognee call used, benchmark method + results, Firedrill results, "providers are fictional", real price list source + date, team names.
- [ ] Make the repo public, upload the video (unlisted YouTube or Loom), submit on the hack page with names + emails.

---

## If you're behind
Cut in this order: SMTP send (keep the sandbox outbox), then SingleStore vector columns, then Persona (show as "next step" text), then diff-view polish.
**Never cut:** Approval #2 send, the fresh-session restart, the idempotent outbox.

## Sync points with Manank (2 minutes each)
- **2:20:** contracts agreed, keys working.
- **2:45:** merge `pipeline` into `main`.
- **3:10:** merge memory + optimizer.
- **3:30:** go/no-go on Firedrill and the benchmark.
- **3:45:** feature freeze.
