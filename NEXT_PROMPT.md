You are continuing a hackathon build already in progress, as the lead engineer. The repo is the `last-wishes` folder. Feature freeze is 3:45 PM PT; submission is 4:00 PM.

## Read first, in this order
1. `HANDOFF.md`: current status, what is verified, blockers, known issues, next steps. Start from its "Next steps" section.
2. `LAST_WISHES.md`: the spec. §3 hard rules, §9 contracts, §10 schema, §11 graph and §18 checkpoints are binding.
3. `LISHA.md` and `MANANK.md`: who supplies what.
4. `contracts.py`: the shared data shapes. Every module imports from it.

## Rules that already held in this build. Keep them.
- Use only `.venv/bin/python` and `.venv/bin/streamlit` (Python 3.12). Never use the system Python (3.14), and don't recreate the venv.
- Run `.venv/bin/python -m pytest -q` before and after every change. The baseline is 108 passed, 1 skipped. Don't commit a regression.
- Commit locally after each working step, with small commits. Don't push, create a GitHub repo or post anything without asking me first.
- Never put secrets in code, commits, logs or chat. Keys live only in `.env`, which is gitignored. If a key is missing, ask me; never invent one.
- Don't guess third-party APIs (Superlinked SIE, Cognee, Persona, Firedrill). The wrappers were written from the real docs; read the docs before changing them. If something is unclear, stop and ask.
- Spec §3: every displayed number comes from running the pipeline on files in `data/`. Nothing is hardcoded or provider-specific. An unknown price is never 0 and is never called "cheapest". Show only "review flag / needs clarification": never "illegal" or "violation". The app never pays; the final state is "Arrangement request sent — awaiting provider confirmation." The LLM only drafts and explains. Each approval covers one message and is invalidated when the quote version changes. Sends happen once.
- SingleStore is the free shared tier: no `CREATE ROWSTORE TABLE`, and **at most 10 tables per database** (all 10 are used). Don't add tables; store new state in existing ones (`audit_log`, `documents`).
- Don't refactor working modules. Fix only what blocks the demo. Don't change the `contracts.py` shapes without telling me.

## Working with parallel agents, if your setup has them
- Give each agent a strict list of the files it owns. No two agents edit the same file. Agents don't commit; you review, run the tests, then commit.
- Give each agent the spec sections it needs and the exact function signatures it must match from `contracts.py` and the existing modules.
- After each agent finishes, check its work yourself: run the tests and the real flow. Then report to me in plain terms what is verified and what isn't.
- Good tasks to run in parallel now: (a) the benchmark in `bench/`, once the SIE key works; (b) Firedrill in `tests/firedrill/`, only if I give you the quickstart link; (c) the full `README.md` per spec §19; (d) the small UI fixes listed in HANDOFF.md "Known issues".
- If you have no agents, do the same work in that order yourself.

## What to do first
1. Run the tests and `git log --oneline` to confirm the baseline.
2. Check which keys in `.env` are now set. Print only whether each is set, never its value. Then run the "Next steps" checks in HANDOFF.md for whatever is unblocked.
3. The critical path is SIE extraction on quotes A, B and C. Then the Compare tab, Approval #1, a real Streamlit restart, the Inbox reply leading to quote v2, the Cognee recall, the diff, the Persona gate, and Approval #2. Never cut any item §18 marks "never cut".
4. At each checkpoint (2:45, 3:10, 3:30, 3:45), tell me honestly what passes, what is stubbed and what fails. Label any cached run a "recorded replay".

Ask me any question whose answer would change behavior. Don't silently pick something that contradicts the md files.
