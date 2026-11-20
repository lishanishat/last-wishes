# Prompt for the build chat

Paste everything below the line into a new Claude Code session opened in the `last-wishes` folder.

---

You are the lead engineer building **Last Wishes** for a hackathon. The deadline is tight: **everything must be working, committed and demo-ready by 3:45 PM**, with submission by 4:00 PM. Work fast, but build it properly.

## Read these first (they are the source of truth)
- `LAST_WISHES.md`: the full spec. The hard rules in §3, the pipeline in §8, the data contracts in §9, the database tables in §10, the Cognee graph in §11, and the checkpoints in §18 are binding.
- `LISHA.md` and `MANANK.md`: the two humans' roles and checkpoints. Use them to decide who needs to supply what (API keys, the real price list, demo recording).

The folder already has `requirements.txt`, `.env.example`, `.gitignore`, and empty `pipeline/`, `memory/`, `data/`, `bench/` and `tests/firedrill/` folders.

## Non-negotiables
1. **A working app, not a hardcoded demo.** Every number shown comes from running the pipeline on files in `data/`. Nothing provider-specific in code. A differently worded reply must still work.
2. Follow §3 exactly: no legal verdicts (only "review flag / needs clarification"), no payment, unknown prices are never zero, the LLM only drafts and explains, each approval covers exactly one message, approvals are invalidated when the quote version changes, an idempotent send, and honest labels.
3. **Don't guess third-party APIs.** Before writing a wrapper, read the real docs:
   - Superlinked SIE: superlinked.com/serverless and github.com/superlinked/cookbook
   - Cognee: docs.cognee.ai
   - SingleStore: the `singlestoredb` Python docs
   - Persona: docs.withpersona.com (sandbox)
   - Firedrill: their hackathon quickstart

   If a doc is unclear or an API needs something we don't have, **stop and ask me**.
4. **Never put secrets in code or git.** Use `.env` (which is gitignored). If a key is missing, ask me for it. Don't create accounts or sign up for anything yourself.
5. Don't push to GitHub, create remote repos, or post anything without asking me first. Local `git init` and commits are fine.
6. **Ask me any question that would change behavior.** Don't silently pick something that contradicts the md files.

## Step 0 (do this first, alone, in under 10 min)
1. `git init`, create a Python venv, `pip install -r requirements.txt`.
2. Create `contracts.py` with the exact §9 shapes as `TypedDict`s (LineItem, Flag, Plan) and the Memory API function signatures. Every agent imports from it.
3. Ask me, in **one message**, for whatever is missing in `.env`: SIE key/URL, SingleStore URL, Cognee/LLM key, Anthropic key, Persona key + template. Also ask whether I have the real price-list PDF yet. Keep working while I answer; agents can build against the contracts with small local test inputs.

## Then run these agents in parallel
Each agent owns only its listed files. No agent edits another agent's files. If an agent needs an interface change, it reports back to you rather than editing someone else's file.

| Agent | Owns | Delivers |
|---|---|---|
| **1. Seed data** | `data/*`, `data/SOURCES.md`, `data/ftc_reference.txt` | Wishes, quotes A/B/C in **different formats**, `reply_A_v2.txt`, `reply_A_alt.txt`, FTC excerpts with URLs (spec §4, MANANK.md CP1). Fictional and labeled. For the real price list: **ask me** for the file/URL; don't download it without approval. |
| **2. SIE pipeline** | `pipeline/sie_client.py`, `pipeline/extract.py`, `pipeline/classify.py` | Real SIE calls. Every call returns trace metadata (recipe, model, latency_ms, input_chars). `extract_quote()` / `classify()` match the contracts, with None for unknown amounts. |
| **3. Rules + optimizer** | `pipeline/flags.py`, `pipeline/optimizer.py` | `review_flags()` (3 code rules, exact flag wording from spec §4), `best_plan()` (unknowns as ranges, a `not_needed` list), `replan()` + diff. Pure functions with unit tests in `tests/`. |
| **4. Cognee memory** | `memory/cognee_mem.py` | The graph from §11. `recall()` returns the real nodes/edges and works **after a process restart**. Includes the counterfactual mode (recall without the "avoid extras" wish). |
| **5. DB + approvals + outbox** | `db.py`, `approvals.py`, `outbox.py` | SingleStore schema from §10 (vectors only if quick). Approval payload hash, invalidation on quote-version change, send-once with a UNIQUE idempotency key, audit_log, sie_calls logging. |
| **6. Persona** | `persona.py` | Sandbox inquiry create → hosted link → status poll. Approval #2 is blocked until the inquiry is `approved`. |
| **7. UI + orchestrator** | `app.py`, `agent.py` | Streamlit tabs: Wishes, Quotes, Compare (flags + Not needed + plan), Approvals, Inbox (reply upload), Memory (query + nodes/edges), Diff, Trace drawer. The app's state rebuilds from the DB + Cognee alone (fresh-session test). Build against the contracts with fakes until the other modules land, then wire in the real ones. |

**After agents 2–5 land**, start these two:

| Agent | Owns | Delivers |
|---|---|---|
| **8. Benchmark** | `bench/` | 10–20 hand-labeled items. SIE vs one general LLM on identical inputs: field accuracy, label accuracy, latency, cost. One-sentence method. Report all results in `bench/results.md`. |
| **9. Firedrill** | `tests/firedrill/` | Only if CP2 is on time. The 3 scenarios from spec §13, results reported as "passed X of Y". |

## Your job as lead
- Keep agents on their files. Merge their work, and run the whole flow end to end yourself after every merge.
- Hit the spec §18 checkpoints and tell me the status at each one:
  - **2:45** data in
  - **3:10** loop 1
  - **3:30** memory + action after a **real Streamlit restart**
  - **3:45** freeze
- If behind, cut in the §18 order. Never cut the items marked "never cut."
- Final verification before 3:45, all from a clean restart with nothing hand-edited in the DB:
  1. The Compare tab fills from real extraction.
  2. A's crematory fee shows as unresolved.
  3. The casket flag shows its excerpt beside the FTC text.
  4. Approval #1 produces exactly one outbox row.
  5. After a restart, uploading the reply creates Quote v2 and keeps v1.
  6. Recall shows the real nodes and edges.
  7. The diff and the replan are correct.
  8. The Persona gate works.
  9. Approval #2 sends once, with the status "Arrangement request sent — awaiting provider confirmation."
  10. `reply_A_alt.txt` also works.
- Then write `README.md` per spec §19: setup, architecture, every SIE recipe and Cognee call used, benchmark and Firedrill results, "providers are fictional", the real price list's source and date, and team names (Lisha, Manank).
- Report honestly. If something is stubbed, cached or failing, say so plainly. Label any cached run as a "recorded replay".

Start with Step 0 now.
