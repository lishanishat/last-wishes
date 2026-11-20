# Last Wishes — Full Project Spec

> **The agent follows up. The family decides.**

Personal Agents Hackathon (tokens&, AWS Builder Loft SF), Fri Nov 20.
Team: **Lisha** + **Manank**. Internal finish target: **4:00 PM** (official deadline 4:30 PM).

Role files: [LISHA.md](LISHA.md) · [MANANK.md](MANANK.md)

---

## 1. One-liner

A personal agent that remembers what a parent wanted, reads funeral quotes against those wishes, follows up on what's missing or questionable, and carries the family's reviewed choice into an approved arrangement request — with evidence for every step.

**Closing line for the demo:** *"Here's what Linda wanted, what the quotes actually include, and what changed after her family asked."*

## 2. Problem

When a parent dies, a family has days to arrange and pay for a funeral (often thousands of dollars) while grieving. Quotes come in different formats, leave prices out, bundle services nobody asked for, and sometimes state "requirements" that aren't required. The family re-explains what their parent wanted, can't compare the quotes, and loses track of what's still unresolved.

The US **FTC Funeral Rule** gives families real protections (itemized prices, choosing only what you want, no false "required" claims, alternative containers for direct cremation) — but almost nobody knows them.

## 3. Hard rules (non-negotiable)

- **Working app, not a hardcoded demo.** Every displayed number comes from running the pipeline on input documents. Seed documents are *inputs*, not scripted outputs. A differently worded reply must still work.
- **No legal verdicts.** Flags say "review flag / needs clarification" and show the provider's excerpt beside the public FTC guidance. Never "illegal" or "violation".
- **No payment.** Final state is "Arrangement request sent — awaiting provider confirmation." Never "Purchased" or "Booked".
- **Unknown ≠ zero.** Missing prices are shown as unresolved or as ranges; a quote with unknowns is never called "cheapest".
- **The LLM only explains and drafts.** It never decides compliance, does math, or approves anything.
- **Each approval covers exactly one message.** If the quote changes after an approval card is prepared, that approval is invalidated.
- **Send once.** Retries never create a duplicate (idempotency key).
- **Honest labels.** Fictional providers are labeled fictional; any cached run is labeled "recorded replay".
- **Tone:** calm, plain, dignified. No cute copy, no sad music, story lands in 15 seconds.

## 4. The scenario (all fictional except the one real price list)

**Linda (78)** recorded her wishes while alive:
> "Keep it simple. Cremation, no public viewing. Please avoid unnecessary extras."

Her **daughter** confirms the preferences and a working budget (~$4,000) and is the app's reviewer. The prototype does not determine legal authority.

| Provider (fictional) | What the document contains | What the agent should do |
|---|---|---|
| **A — Low headline** | Low total, **no crematory fee listed** | Mark crematory fee **unresolved**; never call A "cheapest complete" |
| **B — Complete** | Clean itemized quote for direct cremation | Baseline |
| **C — Package** | A package with viewing/embalming/flowers the family didn't choose **plus** the line *"A casket purchase is required for direct cremation."* | "Not needed" items listed with savings; **one review flag** on the casket statement |
| **Real public price list** | One real, publicly posted General Price List (with source URL + date) | Extraction test only; never mixed with fictional traps |

**The review flag (exact wording):**
> Provider statement: "A casket purchase is required for direct cremation."
> Review flag: "FTC guidance requires an alternative-container option for direct cremation. Ask the provider to clarify this requirement and quote that option."

Show the provider excerpt beside the FTC reference. Do not auto-remove the charge; do not assume the alternative is free. Verify wording on consumer.ftc.gov before recording.

**The provider reply** (fresh session): Provider A answers the clarification, supplying the crematory fee (and possibly a changed term). The agent creates **Quote v2**, keeps v1, replans, and explains what changed.

## 5. The three moments judges should remember

1. **It noticed a questionable requirement** — provider's own words beside the reference.
2. **It followed up and understood the changed quote** — in a fresh session, from memory.
3. **It carried the family's reviewed choice into an arrangement request** — separately approved, identity-verified.

## 6. Sponsors

| Sponsor | Role in Last Wishes | Fit | Status |
|---|---|---|---|
| **Cognee** | Memory of wishes (with sources), quote versions, open questions; the fresh-session recall | Core | Keep |
| **Superlinked SIE** | Extract line items/amounts/requirements/excerpts from quotes and the reply; classify line items; rerank to find source excerpts | Core | Keep |
| **SingleStore** | App database: exact amounts, quote v1/v2, approval versions, send status, audit log; vector search over quote excerpts + FTC text | Strong — we need a DB anyway | Add |
| **Firedrill** | Simulate: quote changes after approval, send fails and is retried, differently worded reply | Strong — tests safety rules | Add if CP1 hit on time |
| **Persona** | Verify the daughter's identity (sandbox) before Approval #2 sends a request on the family's behalf | Decent — says *who she is*, not legal authority | Add |

Cash prizes: Cognee, Superlinked (two tracks). Gift cards: SingleStore, Firedrill. Persona: Keychron gift cards + swag.

## 7. Architecture

```
            ┌──────────── Streamlit UI (app.py) ────────────┐
            │ Wishes · Quotes · Compare · Flags · Approvals │
            │ Inbox (reply upload) · Diff · Graph · Trace   │
            └──────────────┬─────────────────────┬──────────┘
                           │                     │
                 orchestrator (agent.py)    approvals / outbox
                           │                (idempotent send)
     ┌─────────────┬───────┴──────┬──────────────┬──────────────┐
     │             │              │              │              │
 Superlinked    rules/flags    optimizer      Cognee         Persona
 SIE extract    (code)         (code)         memory graph   (sandbox
 classify,                                     add/cognify/   inquiry)
 rerank                                        search
     │             │              │              │
     └─────────────┴──── SingleStore (canonical state + audit + vectors) ───┘
                                   │
                          Firedrill scenarios (tests)
```

**Ownership of truth:**
- **SingleStore** = exact amounts, quote versions, approvals, send status, dedupe, audit log, SIE trace.
- **Cognee** = meaning, relationships, provenance; used for recall and explanation. **Never** enforces approvals.

## 8. Pipeline (step by step)

| # | Step | What happens | Component |
|---|---|---|---|
| 1 | Recall wishes | Linda's note + daughter's confirmation stored with source IDs | Cognee + SingleStore |
| 2 | Read quotes | Extract line items, amounts, price type, inclusions, stated requirements, excerpts | **SIE extract** |
| 3 | Classify | Each item: basic fee / optional / cash advance / package / stated requirement | **SIE classify** |
| 4 | Validate | Every value has an excerpt; missing fields detected; low confidence → reviewer | Code |
| 5 | Normalize | Match comparable services; no double counting in packages; price type = fixed / estimated / starting-at / unknown | Code |
| 6 | Review flags | Evidence-driven only: unresolved charge (A), unselected services (C), casket statement (C) | Code rules + SIE classify; FTC text via SingleStore vector search |
| 7 | Recall context | Relevant wishes, earlier choices, open questions | **Cognee search** |
| 8 | Optimize | Cheapest itemized combination meeting every wish; unknowns as ranges; "Not needed" column with savings | Code |
| 9 | Draft clarification | Narrow, evidence-grounded question to A (and C re: container) | LLM on validated data only |
| 10 | Approval #1 | Daughter approves exact recipient + message → persisted → **sent once** | App + SingleStore outbox |
| 11 | Fresh session | **Restart the app on screen.** Reply arrives via Inbox (upload/paste) | — |
| 12 | Read reply | SIE extracts new charge/changed terms — no provider-specific code | **SIE** |
| 13 | Reconcile | Cognee recall (show real query + returned nodes/edges); create Quote v2, keep v1; mark plan stale | **Cognee** + SingleStore |
| 14 | Replan + explain | Re-run optimizer on v2; diff v1→v2; "You reviewed this while the crematory charge was unresolved. The reply sets it at $X." | Code + LLM explanation |
| 15 | Select | Daughter picks provider + quote version | UI |
| 16 | Identity check | **Persona** sandbox inquiry for the daughter must be `approved` | Persona |
| 17 | Approval #2 | Card: provider + recipient, exact quote version, services, known/estimated/unresolved totals, exact message → "Approve and send arrangement request" | App |
| 18 | Send + receipt | "Arrangement request sent — awaiting provider confirmation." Evidence receipt links each line to wish, excerpt, quote version | App + SingleStore |

## 9. Data contracts (agreed interfaces — don't change without telling the other person)

```python
# LineItem (dict) — produced by pipeline/extract.py
{
  "item_id": "B-03",
  "quote_id": "B-v1",
  "provider": "B",
  "name": "Direct cremation (basic)",
  "category": "basic_fee|optional|cash_advance|package|stated_requirement",
  "price_type": "fixed|estimated|starting_at|unknown",
  "amount_low": 1195.0,      # None if unknown
  "amount_high": 1195.0,     # None if unknown
  "excerpt": "Direct cremation ... $1,195",
  "source_doc": "quote_B.pdf",
  "confidence": 0.93
}

# Flag
{"flag_id": "C-F1", "quote_id": "C-v1", "item_id": "C-07",
 "kind": "unresolved_charge|not_selected|stated_requirement",
 "excerpt": "...", "reference": "FTC Funeral Rule guidance: ...", "message": "..."}

# Plan  — produced by pipeline/optimizer.py
{"plan_id": "...", "quote_id": "B-v1", "items": [item_id, ...],
 "known_total": 2390.0, "estimated_low": 0, "estimated_high": 150,
 "unresolved": ["A: crematory fee"], "not_needed": [{"item_id":..., "savings":...}],
 "wishes_satisfied": ["W1","W2","W3"]}

# Memory API — memory/cognee_mem.py
remember_wish(text, source_id) -> node_id
remember_quote(quote_id, provider, version, items, supersedes=None)
remember_question(question_id, quote_id, item_name)
remember_reply(reply_id, question_id, new_quote_id)
recall(query: str) -> {"answer": str, "nodes": [...], "edges": [...]}
```

## 10. SingleStore schema (Lisha owns)

```sql
wishes(id, text, source_id, confirmed_by, confirmed_at)
documents(id, kind, provider, filename, is_fictional, source_url, captured_at, raw_text)
quotes(id, provider, version, supersedes_id, document_id, created_at)
line_items(id, quote_id, name, category, price_type, amount_low, amount_high,
           excerpt, confidence, excerpt_vec VECTOR(…))
flags(id, quote_id, item_id, kind, excerpt, reference, message)
plans(id, quote_id, known_total, est_low, est_high, unresolved_json, stale BOOL)
approvals(id, kind, quote_id, payload_hash, status, approved_by,
          persona_inquiry_id, created_at, invalidated_at)
outbox(id, approval_id, idempotency_key UNIQUE, recipient, body, status, attempts)
audit_log(id, ts, actor, action, detail_json)
sie_calls(id, ts, recipe, model, latency_ms, input_chars, output_json)
ftc_reference(id, text, url, text_vec VECTOR(…))
```

## 11. Cognee graph (Manank owns)

- Person(Linda) → STATED → Wish → SOURCED_FROM → Document(span)
- FamilyMember(daughter) → CONFIRMED → Wish; → HAS_ROLE → Reviewer
- Provider → OFFERS → Quote(v1, v2) → CONTAINS → LineItem
- Quote(v2) → SUPERSEDES → Quote(v1)
- LineItem → SATISFIES / CONFLICTS_WITH → Wish
- Question → ABOUT → LineItem (unresolved); Reply → ANSWERS → Question
- Plan → BASED_ON → Quote; Plan → HONORS → Wish

**Cognee judge asks for:** live restart; show the real query and returned nodes/edges; graph before/after the reply; one **counterfactual** (remove "avoid extras" → wrong call); one sentence on *why a graph*: *"The reply only makes sense through its links — to the question we asked, the quote it changes, the plan built on that quote, and the wish that plan honors."*

## 12. Superlinked must-haves

- Live extraction on the **real price list** (show where it struggles).
- Casket flag comes from **SIE classify + code rule**, not the LLM.
- **Trace drawer**: recipe, model, latency, excerpt for each SIE call (from `sie_calls` table).
- **Benchmark table**: 10–20 hand-labeled line items, SIE vs a general LLM on the same inputs: field accuracy, label accuracy, latency, cost. One-sentence method. Report all results.

## 13. Firedrill scenarios (if CP1 on time)

1. Quote changes after Approval #2 card is prepared → approval invalidated, new card shown.
2. Send fails then retried → exactly one outbox row sent.
3. Differently worded provider reply → still extracts the new charge.
Report "passed X of Y", never "never fails".

## 14. Persona (sandbox)

Before Approval #2, the daughter completes a Persona sandbox inquiry (hosted flow). App checks inquiry status = approved via API and stores `persona_inquiry_id` on the approval. Copy: "Persona verifies who is approving — not legal authority."

## 15. Demo script (2.5 min)

1. **(15s)** Linda's recorded note + daughter's confirmed preferences.
2. **(30s)** Three quotes compared. A's crematory fee unresolved. C's casket line flagged beside FTC guidance. "Not needed" column with savings.
3. **(20s)** Daughter approves clarification → sent once.
4. **(40s)** **Restart the app.** Reply arrives in Inbox → Cognee recall (show query + graph path) → Quote v2 (v1 kept) → replan → "what changed and why".
5. **(25s)** Daughter selects → Persona verification → Approval #2 → "Arrangement request sent — awaiting provider confirmation."
6. **(20s)** Trace drawer + benchmark + Firedrill results. Closing line.

## 16. Judge Q&A

- **Is this a purchase?** It turns the family's reviewed choice into an approved, identity-verified arrangement request. The family decides; the provider confirms; the agent never pays.
- **Legal advice?** No. It shows the provider's own words beside public FTC guidance and suggests a question.
- **Is memory essential?** Watch the restart: no chat history, and it still knows what Linda wanted and what was pending. Remove one memory link and it gets it wrong.
- **Why small models?** Trace drawer + benchmark.
- **Real data?** One real public price list (source + date shown); providers are fictional and labeled.

## 17. Judging history (simulated, fictional composite judges)

Three rounds, 4 judges each (Superlinked, Cognee, main panel, strategist). Last Wishes won every round:
- vs PartSnap / SwapCircle — Last Wishes ranked 1st by all.
- vs MissionCart — Superlinked 8/7 vs 5/6; Cognee 8 vs 3; panel originality 9 vs 5.
- vs SetupAI — Superlinked 8/8 vs 5/6; Cognee 8 vs 4; panel originality 9 vs 4, buildability 7 vs 3.
Teammate ideas folded in: itemized-plan optimizer, whole-plan replan on quote change, requirement checker, "Not needed" column, benchmark.

## 18. Timeline & checkpoints (finish by 4:00)

| By | Checkpoint | Must be true |
|---|---|---|
| **2:20** | CP0 — Setup | Repo live, both can push; keys work: SIE, Cognee (+LLM key), SingleStore, Persona sandbox; contracts in §9 agreed |
| **2:45** | CP1 — Data in | Extraction runs on A, B, C + real list → line items in SingleStore; wishes in Cognee; UI shows comparison table |
| **3:10** | CP2 — Loop 1 | Flags + unknowns + optimizer + "Not needed"; Approval #1 → outbox sends once; Inbox reply → SIE → Quote v2 stored |
| **3:30** | CP3 — Memory + action | Restart → Cognee recall shown; diff v1→v2; replan; Persona check; Approval #2 → arrangement request sent |
| **3:45** | CP4 — Freeze | Trace drawer, benchmark table, Firedrill results (if added); full run rehearsed twice |
| **4:00** | CP5 — Submitted | Demo video recorded + link; README; repo public; submission form done |

**If behind at a checkpoint, cut in this order:** Firedrill → benchmark polish → SingleStore vector search (keep plain SQL) → Persona (show as "next step") → optimizer polish.
**Never cut:** extraction on real inputs, the casket flag, the fresh-session restart + Cognee recall, v1→v2 diff, Approval #2 send.

## 19. Submission checklist

- [ ] GitHub repo (public or judges have access)
- [ ] Demo video link (≤ 3 min)
- [ ] Description: what we built + tools used (Cognee, Superlinked SIE, SingleStore, Firedrill, Persona)
- [ ] Team names + contact emails
- [ ] README: setup, `.env.example`, architecture, every SIE recipe and Cognee call used, benchmark method + results, Firedrill results, "providers are fictional" note, real price list source + date
- [ ] Screenshot
