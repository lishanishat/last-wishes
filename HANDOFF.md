# HANDOFF - Last Wishes build status

Refreshed Fri Nov 20 2026, afternoon PT, for submission. Internal deadline: submit by 4:00 PM (official 4:30). The repo is pushed and public at https://github.com/lishanishat/last-wishes. History was rewritten once to drop attribution trailers; the backup branch `backup-before-rewrite` is local only and must not be pushed.

Read first: `README.md` (what is and is not verified), `LAST_WISHES.md` (spec; section 3 hard rules are binding), `DEMO_SCRIPT.md`, `SUBMISSION.md`.

## Environment
- Python 3.12 venv at `.venv/`. Use `.venv/bin/python` and `.venv/bin/streamlit`, including for the on-camera restart (system Python 3.14 is unsupported by Cognee).
- Run the app: `.venv/bin/streamlit run app.py` (http://localhost:8501). Tests: `.venv/bin/python -m pytest -q` (111 passed, 1 skipped; the skip is the live Persona test).
- `requirements.txt` plus `requirements.lock.txt`.

## `.env` (gitignored, never committed) - status only
| Var | Status |
|---|---|
| `SINGLESTORE_URL` | set, verified live |
| `SIE_API_KEY`, `SIE_BASE_URL` | set, verified live |
| `PERSONA_API_KEY`, `PERSONA_TEMPLATE_ID` | set (sandbox); live end-to-end approval not confirmed in docs |
| `LLM_API_KEY` | not set |
| `ANTHROPIC_API_KEY` | not set (drafting uses the labeled template fallback) |

The SingleStore password appeared in chat screenshots: reset it after submission and do not show the Connect panel on camera. A secrets scan of the working tree and all git history found no keys or credentials in tracked files.

## What works and is verified
- Quote extraction and classification through SIE (`extract`, `classify`, `rerank` recipes) on quotes A/B/C, both replies, and the public price list (live, 2026-11-20).
- Code-side rules, flags (review flag wording, no legal verdicts), optimizer, replanning and diff; offline tests.
- SingleStore storage (columnstore outbox, 10-table cap); duplicate idempotency key rejected on live SingleStore.
- Cognee graph memory survives a real Streamlit restart; recall returns real nodes and edges.
- Benchmark: SIE 36/39 price fields, 13/13 categories; Qwen chat 39/39, 11/13 (`bench/results.md`).
- Firedrill platform: 2 of 2 scenarios met threshold; only 2 of 6 ran on the platform, on Manank's own pipeline copy with a stand-in for approvals/outbox (`tests/firedrill/PLATFORM_SCORES.md`).

## Remaining gaps (be honest on camera and in the form)
1. No LLM key: drafts are a labeled template; Cognee's `add`/`cognify` LLM layer and LLM recall answer are untested live.
2. Persona: completing the hosted flow reports `completed`, not `approved`; the demo path uses the sandbox "Simulate approval" button. Confirm it reaches `approved` before recording (DEMO_SCRIPT.md).
3. Real price list extraction also yields price-less guidance sentences as candidates (known limitation, kept separate from the fictional comparison).
4. Cold SIE models can take minutes: warm up before recording.
5. Firedrill campaign state still read "running" when scores were fetched.

## Rehearsal 1 (live app)
- Steps 1-5 and 8 passed.
- `reply_A_alt` crash fixed in fb1f8ae. B $50 dropped-item fix in 0d36355.
- Approval #2 send was **not observed** in rehearsal 1. It is being re-run by another agent; do not state it passed until that result is in.

## Real-world benchmark
Manank reports a held-out run (8 public price lists, 137 items: found 81.8%, amount 93.8%, price type 72.3%, category 48.2%, all four 41.6%). Not re-run here; `bench/realworld/results.md` is not in the repo yet. README states this.

## What Lisha must do by hand
See the checklist in `SUBMISSION.md` (demo video with on-camera restart, screenshot, form, password reset). Senso is not part of the build.
