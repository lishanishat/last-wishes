# Last Wishes demo (3 minutes max)

Record the live app. Providers are fictional. Read amounts from the screen, not from this script.

## Step 1: Drop in the documents (about 1:00)
- Click **Load wishes**. "Linda wanted cremation, no public viewing, no unnecessary extras. Maya, her daughter, confirmed that."
- Read quotes A, B, C. "A's crematory fee is Unresolved, so its low headline is not the cheapest complete plan. C includes services Linda did not choose; they show as Not needed savings."
- C's casket line is flagged beside the public FTC text. "A review flag, not a legal verdict."
- Approve the one clarification. "Maya approves this exact message once; the sandbox outbox sends it once."

## Step 2: The agent says the next step (about 1:00)
- Stop Streamlit on camera and restart: `.venv/bin/streamlit run app.py`.
- Paste or upload `data/reply_A_v2.txt`.
- Quote v2 appears with v1 kept. Show the diff and "what changed". Open Memory: recall nodes and edges returned after the restart.

## Step 3: The human approves (about 0:50)
- Select A-v2. Run the Persona sandbox check: use the sandbox-only simulate button and say it is sandbox. It verifies who is approving, not legal authority.
- Approval #2 -> "Arrangement request sent — awaiting provider confirmation." The app never pays or books.
- Close: **"Here's what Linda wanted, what the quotes actually include, and what changed after her family asked."**

## Pre-record checklist
- [ ] Warm SIE with one extraction (cold models can take minutes).
- [ ] Reset demo data.
- [ ] Close the browser tab with the SingleStore Connect panel.
- [ ] Do not show `.env`.
- [ ] Label any cached footage "recorded replay".
- [ ] Drafts are template-labeled unless `ANTHROPIC_API_KEY` is set; say so if asked.
- [ ] Confirm Persona sandbox reaches `approved` and Approval #2 sends before recording.
