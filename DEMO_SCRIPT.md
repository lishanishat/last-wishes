# Last Wishes demo cue sheet (target: 2½ minutes)

Record the live app. Keep the providers marked fictional, show the actual SIE trace and Cognee results, and stop/restart Streamlit on screen. Follow the app's current figures rather than reading amounts from this script.

| Time | Screen | Narration |
|---|---|---|
| 0:00–0:15 | Wishes | “Linda wanted cremation, no public viewing, and no unnecessary extras. Maya, her daughter, confirmed those wishes and a working budget. The agent keeps each wish with its source.” |
| 0:15–0:45 | Quotes → Compare | “Three fictional providers sent quotes in different formats. The agent reads their own words. A leaves the crematory fee unresolved, so its low headline is not treated as the cheapest complete plan. B is itemized. C includes services Linda did not choose.” |
| 0:45–1:00 | C review flag | “C also says a casket purchase is required for direct cremation. We place that exact statement beside public FTC guidance and ask for clarification. This is a review flag, not a legal verdict.” |
| 1:00–1:20 | Approvals | “Maya reviews one exact clarification message and recipient. The sandbox outbox sends that approved message once.” |
| 1:20–1:55 | Stop and restart Streamlit → Inbox → Memory → Diff | “After a real restart, A's reply arrives. Cognee recalls the question, quote, and wishes through returned graph nodes and edges. SIE reads the new fee and revised refrigeration price. A-v2 supersedes A-v1; the unchanged certificate estimate is not counted twice. Here is the line-by-line change and new plan.” |
| 1:55–2:20 | Approvals + Persona | “Maya selects the version she wants. Persona sandbox verifies who is approving, not her legal authority. She reviews the exact services, quote version, totals, and recipient, then approves a separate arrangement request. The app does not pay. The provider still has to confirm.” |
| 2:20–2:30 | Trace and benchmark | “These are the SIE recipe/model traces and the complete 13-line benchmark results, including misses.” |

Closing line: **“Here's what Linda wanted, what the quotes actually include, and what changed after her family asked.”**

Before recording, check that the Persona sandbox inquiry can reach `approved` and Approval #2 can send. Firedrill platform results have not arrived; do not narrate them as completed. Label any cached footage **recorded replay**.
