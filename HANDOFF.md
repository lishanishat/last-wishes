# HANDOFF — Last Wishes build status (for the next Claude session)

Written Fri Nov 20 2026, ~1:55 PM PT. Internal deadline: feature freeze 3:45 PM, submit 4:00 PM (official 4:30).

**Read first:** `LAST_WISHES.md` (spec — §3 hard rules, §8 pipeline, §9 contracts, §10 schema, §11 graph, §18 checkpoints are binding), `LISHA.md`, `MANANK.md`. This session was driven by the "Prompt for the build chat" (lead engineer + parallel agents; each agent owns only its files; no pushing to GitHub / creating remote repos / posting without asking Lisha; never put secrets in code or git; don't guess third-party APIs — read the docs; ask Lisha about anything that changes behavior).

## Environment
- **Python 3.12 venv at `.venv/`** (system Python is 3.14, which Cognee doesn't support). Always use `.venv/bin/python` and `.venv/bin/streamlit` — including the on-camera restart.
- `requirements.txt` (top level) + `requirements.lock.txt` (`pip freeze`). Added during build: `sie-sdk==0.11.1`, `pyturso>=0.7.2,<0.8`. `pytest` is in the venv. If the real price list is a PDF, `pypdf` still needs adding.
- Local git only (`git init`), all work committed on `master`. **No remote, nothing pushed.** LISHA.md wants a GitHub repo `last-wishes` with `main` / `ui` / `pipeline` branches — ask Lisha before creating/pushing.
- Run the app: `.venv/bin/streamlit run app.py` → http://localhost:8501
- Run tests: `.venv/bin/python -m pytest -q` → **108 passed, 1 skipped** (the skip is the live Persona test).

## `.env` (gitignored) — status
| Var | Owner | Status |
|---|---|---|
| `SINGLESTORE_URL` | Lisha | **SET and verified** (free Shared/Starter cluster `last-wishes`, AWS US East 1, db `db_lisha_223bf`, port 3333). Password was shown in chat screenshots — reset it after the hackathon; don't show the Connect panel on camera. |
| `SIE_API_KEY`, `SIE_BASE_URL` | Manank | **MISSING** — main blocker. Base URL defaults to `https://api.superlinked.com`. |
| `LLM_API_KEY` (Cognee) | Manank | MISSING. If only `ANTHROPIC_API_KEY` is set, the memory module maps it over. Set `LLM_MODEL` to a cheaper model (Cognee's default here would be `anthropic/claude-opus-5-5`); if cognify 400s on temperature, change `LLM_MODEL`. |
| `ANTHROPIC_API_KEY` | Lisha | MISSING — drafting uses a labeled template fallback until set. |
| `PERSONA_API_KEY`, `PERSONA_TEMPLATE_ID` | Lisha | MISSING (sandbox key `persona_sandbox_…`, template `itmpl_…`). |
| Real price list `data/real_gpl.pdf` + URL + date in `data/SOURCES.md` | Manank | MISSING — don't download one without Lisha's approval. |
| Firedrill hackathon quickstart link | Manank | MISSING. |

## What exists (all committed)
| File(s) | What | Verified |
|---|---|---|
| `contracts.py` | §9 TypedDicts. Changes vs spec (tell Manank): `Plan.estimated_high` may be `None` (open-ended "starting at"); `Plan.notes` optional list; `NotNeeded.savings` may be `None` (unknown price); `extract_quote`/`classify` return `(items, traces)`; `recall(query, exclude_wish_ids=...)`. `estimated_high` covers priced items only — never show known+est_high as a ceiling while `unresolved` is non-empty. | — |
| `data/` | Wishes (W1 cremation, W2 no viewing, W3 avoid extras, W4 budget $4,000; daughter = Maya Marsh), fictional quotes A (Harborview, table, crematory "TBC"), B (Cedar Grove, prose, complete), C (Willowbrook, bullets, package + "A casket purchase is required for direct cremation."), `reply_A_v2.txt` + `reply_A_alt.txt` (crematory $395, refrigeration $150→$195), `ftc_reference.txt` (FTC-1..4, **checked against consumer.ftc.gov 2026-11-20**), `SOURCES.md` (has ground-truth notes). | Totals checked |
| `pipeline/sie_client.py`, `extract.py`, `classify.py` | SIE via `sie_sdk.SIEClient`: extract `fastino/gliner2-large-v1`, classify `fastino/GLiNER2.5-Decide`, rerank `Qwen/Qwen3-Reranker-4B`. Money/price types parsed in code from verbatim excerpts; unknown → None, never 0. Orchestrator must call `classify()` (extract sets placeholder category). Cold models can take minutes — warm up before recording. | 32 offline tests; **never run live** |
| `pipeline/wishes.py`, `flags.py`, `optimizer.py` | Code-only rules (3 flag kinds, exact §4 casket message), `best_plan`, `replan`+diff, `merge_quote`, `budget_status`. C's casket is kept (not auto-removed) and adds unresolved "alternative container (price not quoted)". | 30 tests + run on seed ground truth: B chosen, A never chosen while fee unknown |
| `memory/cognee_mem.py` | §11 graph via Cognee DataPoints + `add_data_points`; `recall()` returns real nodes/edges (`cognee.search(GRAPH_COMPLETION, only_context=True)`); counterfactual; `graph_snapshot`, `reset_memory`. Uses `GRAPH_DATABASE_PROVIDER=turso` (kuzu needs Homebrew openssl@3, not installed) + local fastembed embeddings. Storage in `.cognee_system/` `.cognee_data/` (gitignored). | 8 tests incl. recall in a fresh subprocess; LLM path untested |
| `db.py`, `approvals.py`, `outbox.py` | SingleStore (sqlite dev fallback `.lw_dev.sqlite` only if no URL). **Shared-tier limits handled:** no ROWSTORE (outbox is columnstore with PK+shard key on `idempotency_key`), **max 10 tables** (FTC refs stored as `documents` rows `kind='ftc_reference'`). Vector columns not created (TODO, `LW_VECTOR_DIM`). | 13 tests; duplicate idempotency key rejected **on live SingleStore** |
| `persona.py` | Inquiry create (one-time link), status, `simulate_approve` (sandbox). Completing the hosted flow → `completed`, NOT `approved`; plan is the "Simulate approval (sandbox only)" button. | 12 offline tests; not live |
| `agent.py`, `app.py`, `drafting.py` | Orchestrator + Streamlit tabs Wishes · Quotes · Compare · Approvals · Inbox · Memory · Diff + SIE trace drawer. State rebuilt from DB + Cognee every run (UI state like selection, persona inquiry, last diff kept as audit_log events). Drafts reject LLM output with dollar figures not in the facts or the words illegal/violation/purchased/booked. | 13 tests; app runs on SingleStore and loads wishes |
| `.claude/launch.json` | streamlit launch config | — |

## Known issues / small fixes
1. Wishes tab shows W1 and W2 both as "Cremation, no public viewing." — should display "Cremation" / "No public viewing" separately (wish parsing is sentence-level).
2. Wishes say "confirmed by daughter" — could say "Maya (daughter)".
3. explain_change text grammar: "while the crematory charges was unresolved" (reuses item name).
4. Agent.py merges v2 itself (IDs like `A-05.v2`, new reply items `A-R01`), not the optimizer's `merge_quote` — fine, just be aware.
5. Persona simulate-actions body and `Persona-Version: 2026-09-29` unverified live.
6. Senso is not part of the build (not in spec sponsors).

## Next steps (in order)
1. As keys land: run `.venv/bin/python -m pipeline.extract data/quote_C.txt C-v1` — check the casket sentence classifies as `stated_requirement` and the Decide response shape matches. Then A, B, replies.
2. In the app from a reset: Load wishes → Read quotes A/B/C → Compare (A unresolved, C casket flag beside FTC text, Not needed column, B chosen) → Approval #1 → exactly one outbox row.
3. **Restart Streamlit for real** → Inbox upload `reply_A_v2.txt` → Quote v2 created, v1 kept → Memory tab recall shows real nodes/edges → Diff + replan correct.
4. Persona: create inquiry → hosted link → simulate approve → Approval #2 → "Arrangement request sent — awaiting provider confirmation." sent once. Also test `reply_A_alt.txt`.
5. Launch benchmark agent (`bench/`, 10–20 hand-labeled items, SIE vs one general LLM, report all results in `bench/results.md`) once SIE works; Firedrill (`tests/firedrill/`, 3 scenarios from §13, "passed X of Y") only if on time and the quickstart link arrives.
6. Checkpoint statuses to Lisha at 2:45 / 3:10 / 3:30 / 3:45. Cut order if behind is in §18; never cut extraction on real inputs, the casket flag, the fresh-session restart + Cognee recall, v1→v2 diff, Approval #2 send.
7. Write the full `README.md` per spec §19 (currently only a setup note), demo video, then ask Lisha before creating the GitHub repo / pushing.
