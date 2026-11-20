# HANDOFF - Last Wishes build status

Refreshed Fri Nov 20 2026, afternoon PT, for submission. Internal deadline: submit by 4:00 PM (official 4:30). Everything is committed locally on `master`. **No remote exists and nothing has been pushed.**

Read first: `README.md` (what is and is not verified), `LAST_WISHES.md` (spec; section 3 hard rules are binding), `DEMO_SCRIPT.md`, `SUBMISSION.md`.

## Environment
- Python 3.12 venv at `.venv/`. Use `.venv/bin/python` and `.venv/bin/streamlit`, including for the on-camera restart (system Python 3.14 is unsupported by Cognee).
- Run the app: `.venv/bin/streamlit run app.py` (http://localhost:8501). Tests: `.venv/bin/python -m pytest -q` (baseline 109 passed, 1 skipped; the skip is the live Persona test).
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

## What Lisha must do by hand
See the checklist in `SUBMISSION.md` (GitHub push needs her approval, demo video with on-camera restart, screenshot, form, password reset). Senso is not part of the build.
