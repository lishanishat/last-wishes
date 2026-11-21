# Submission text (copy and paste)

## Project name
Last Wishes

## Description
Last Wishes helps a family compare funeral quotes against a parent's recorded wishes. It reads each provider's own words with Superlinked SIE (entity extraction, a classification step, and an optional reranker), parses money in code, and flags unknown prices instead of treating them as zero. A review flag places one provider's casket statement beside public FTC guidance and asks for clarification; it gives no legal verdict. Cognee keeps a graph of wishes, quotes, questions, and replies, and after a real app restart it recalls the pending question as actual graph nodes and edges. SingleStore holds the exact state: quote versions, approvals, audit records, and a send-once outbox. A Persona sandbox identity check gates the final step, which only sends the family's approved arrangement request ("awaiting provider confirmation"); the app never pays or books. Benchmark: on 13 hand-labelled lines, the SIE pipeline got 36/39 price fields and 13/13 categories versus 39/39 and 11/13 for a general chat model (full results, including misses, in the repo). Firedrill: 2 of 2 scenarios passed on the platform, run on a copy of our pipeline with a stand-in for approvals/outbox; the other four scenarios ran as local tests only. Separately, Manank reports a held-out test on 8 real public price lists (137 items): 81.8% of items found, 93.8% of those with the right amount, but only 48.2% with the right category; not re-run in this repo, which is why every send needs human approval. Providers and people in the demo are fictional; one real public price list is used for an extraction test only. Not verified live: LLM-written drafts (a labeled template is used without an API key) and Cognee's LLM cognify layer.

## Tools used
Cognee, Superlinked SIE, SingleStore, Persona (sandbox), Firedrill.

## Team
- Lisha - email: [LISHA_EMAIL]
- Manank - email: [MANANK_EMAIL]

## Links
- Repo: https://github.com/lishanishat/last-wishes
- Demo video (3 min or less): [VIDEO_URL]
- Screenshot: [attach]

## Checklist for Lisha (by hand)
- [x] Repo is pushed and public (https://github.com/lishanishat/last-wishes). `.env` is gitignored and was never committed.
- [ ] Warm up SIE (one extraction) and click Reset demo data before recording. Approval #2 was confirmed to send in rehearsal; Persona approval there was the sandbox simulate button.
- [ ] Record a demo video of 3 minutes or less following `DEMO_SCRIPT.md`, including the on-camera Streamlit stop/restart (use `.venv/bin/streamlit run app.py`). Do not show the SingleStore Connect panel or `.env`. Label any cached footage "recorded replay".
- [ ] Take a screenshot (for example the Compare tab with the review flag, or the Memory tab after restart).
- [ ] Fill in emails and links above and submit the form by 4:00 PM (official deadline 4:30 PM).
- [ ] After submitting, reset the exposed SingleStore password (it appeared in chat screenshots) and update `.env`.
