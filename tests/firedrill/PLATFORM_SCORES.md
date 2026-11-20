# Firedrill platform run (real platform, not local pytest)

Run through the `firedrill` CLI on workspace "Manny Lizzy", 2026-11-20 ~23:00 UTC. Campaign `8a1c6958-7bd5-43fc-89b5-d6d5f8b36ce8`
(world "Last Wishes drills s3-reworded-reply+s5-casket-wording", 2 drills, 1 repetition each, reset per drill).
Scores come from Firedrill's own simulated users and rubric evaluations (threshold 75), read from `firedrill report <campaign> --json`.

| Scenario | Assessed | Met threshold | Quality score |
|---|---|---|---|
| s3 reworded reply still yields the crematory charge | 1 of 1 | yes | 98.25 |
| s5 casket flag wording (no "illegal"/"violation") | 1 of 1 | yes | 94.5 |

**Passed 2 of 2 on the platform.** Notes: the campaign state still read "running" when these scores were fetched; only 2 of the 6
scenarios were run on the platform (credits); the other 4 scenarios ran only as local pytest. The agent under test used the local
deterministic parser (the platform plan passes no environment), and approvals/outbox is the stand-in, not the real modules.
Open the campaign in the web app under Simulations for the conversations and evidence behind each score.
