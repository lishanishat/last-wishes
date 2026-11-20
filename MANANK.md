# Manank — Role & Checkpoints

**You own:** seed data, the **Superlinked SIE** pipeline (extract / classify / rerank), review flags, the itemized-plan optimizer and replan, **Cognee** memory, the SIE-vs-LLM benchmark, and **Firedrill** scenarios.

**Lisha owns:** the repo/GitHub, Streamlit UI, SingleStore, approvals + outbox, Persona, integration, README, video, submission. See [LISHA.md](LISHA.md). Full spec: [LAST_WISHES.md](LAST_WISHES.md).

**Your code lives in:** `pipeline/`, `memory/`, `data/`, `bench/`, `tests/firedrill/`. Lisha merges into `main`.

**GitHub without `gh`:** plain `git clone` / `git push` over HTTPS with a personal access token works, and so does GitHub Desktop. If either is a hassle, zip or AirDrop your folders to Lisha at each checkpoint and she commits them. Don't lose time on tooling.

**Shared rule:** return exactly the dict shapes in LAST_WISHES.md §9 (LineItem, Flag, Plan, Memory API). Lisha's UI depends on them. If you must change a shape, tell her first.

---

## Tasks by checkpoint

### CP0 — by 2:20 — Setup
- [ ] Get a **Superlinked SIE** key and run one call from the cookbook (github.com/superlinked/cookbook). Note which recipes you have: extract, classify, rerank.
- [ ] `pip install cognee`, set its LLM key, and run `add` → `cognify` → `search` on one sentence.
- [ ] Agree the §9 contracts with Lisha (2 min).

### CP1 — by 2:45 — Data in
- [ ] **Seed data in `data/`** (write fast, realistic, clearly fictional):
  - `wishes_linda.txt`: "Keep it simple. Cremation, no public viewing. Please avoid unnecessary extras." plus the daughter's confirmation (budget ~$4,000).
  - `quote_A.txt`: low headline total, **no crematory fee**.
  - `quote_B.txt`: complete itemized direct cremation.
  - `quote_C.txt`: package with viewing, embalming and flowers, plus the line *"A casket purchase is required for direct cremation."*
  - Use **different formats** for each (table, prose, bullet list) so extraction is real work.
  - `reply_A_v2.txt`: Provider A's reply supplying the crematory fee, worded differently from the quote.
  - `reply_A_alt.txt`: a second, differently worded version for Firedrill.
  - `real_gpl.pdf`: one real, publicly posted price list. Many California funeral homes post theirs online. Record the URL + date in `data/SOURCES.md`.
  - `ftc_reference.txt`: short excerpts from consumer.ftc.gov Funeral Rule guidance (alternative container, itemized prices, no false "required" claims), with URLs.
- [ ] `pipeline/sie_client.py`: thin wrapper. Every call returns `(result, {recipe, model, latency_ms, input_chars})` so Lisha can log it to `sie_calls`.
- [ ] `pipeline/extract.py`: `extract_quote(text, source_doc, quote_id) -> list[LineItem]`, using **SIE extract**. Must produce `price_type` and `excerpt`, and `amount_low/high = None` when unknown.
- [ ] `memory/cognee_mem.py`: `remember_wish()` for Linda's note and the confirmation, each with a source ID.
- ✅ **Check:** running `extract_quote` on A, B, C and the real list returns sensible LineItems, and A has its crematory fee missing rather than set to $0. Push or hand to Lisha.

### CP2 — by 3:10 — Loop 1
- [ ] `pipeline/classify.py`: **SIE classify** each item into `basic_fee | optional | cash_advance | package | stated_requirement`.
- [ ] `pipeline/flags.py`: `review_flags(items, wishes) -> list[Flag]`. Rules in **code**:
  - unresolved charge (an essential service with no price)
  - not selected (classified optional and conflicting with "avoid extras" / "no viewing")
  - stated requirement (SIE classify says `stated_requirement` **and** the text matches casket + cremation): attach the FTC excerpt and the exact flag message from spec §4
- [ ] `pipeline/optimizer.py`: `best_plan(quotes, wishes) -> Plan`. Choose the cheapest itemized set meeting every wish; unknowns become ranges, never zero; build the `not_needed` list with savings. Brute force is fine at this size.
- [ ] `memory/cognee_mem.py`: `remember_quote()`, `remember_question()`, `remember_reply()` (build the graph in spec §11; v2 SUPERSEDES v1).
- [ ] `extract_quote` must work on `reply_A_v2.txt` with **no provider-specific code**.
- ✅ **Check:** flags come out for A (unresolved) and C (not selected + casket), the plan never calls A cheapest, and the reply yields the new crematory fee.

### CP3 — by 3:30 — Memory + replan
- [ ] `recall(query) -> {answer, nodes, edges}` from **Cognee search**. Return the real nodes and edges it returned, not a pretty animation.
- [ ] Recall must work **after a process restart** (Cognee persists to disk/DB). Test this yourself.
- [ ] **Counterfactual:** a function or flag to run recall without the "avoid extras" wish, so the demo can show the wrong result without it.
- [ ] `replan(old_plan, new_quote) -> (new_plan, diff)` where `diff` lists the changed items, old/new amounts, and resolved unknowns.
- [ ] `explain_change(diff, recall)`: a short LLM explanation using validated data only, e.g. "You reviewed this while the crematory charge was unresolved. The reply sets it at $X."
- ✅ **Check:** restart Python, call `recall("What was pending with Provider A?")`, and get the pending question plus Linda's wish back.

### CP4 — by 3:45 — Prove it
- [ ] **Benchmark** (`bench/run.py` → `bench/results.md`):
  - Hand-label 10–20 line items across the quotes and the real list.
  - Run SIE extract+classify against one general LLM on identical inputs.
  - Report field accuracy, label accuracy, latency, and cost (estimated).
  - Write a one-sentence method. **Report all results, including where SIE loses.**
- [ ] **Firedrill** (only if CP2 was on time; check their hackathon quickstart):
  1. The quote changes after the Approval #2 card is prepared → the approval must be invalidated.
  2. The send fails and is retried → exactly one send.
  3. A differently worded reply (`reply_A_alt.txt`) → the new charge is still extracted.
  - Write the results to `tests/firedrill/results.md` as "passed X of Y".
- [ ] Feature freeze at 3:45. Rehearse with Lisha.

### CP5 — by 4:00
- [ ] Narrate your part of the demo video (pipeline + benchmark), about 30 seconds.
- [ ] Give Lisha README lines: the SIE recipes used, the Cognee calls used, the benchmark method, the Firedrill results, data sources.

---

## If you're behind
Cut in this order: Firedrill, then benchmark size (5 items is fine), then rerank, then counterfactual polish.
**Never cut:** real extraction (no hardcoded numbers), the casket flag, Cognee recall after restart, Quote v2 keeping v1.

## Sync points with Lisha (2 minutes each)
- **2:20:** contracts and keys.
- **2:45:** hand over extract + seed data.
- **3:10:** hand over flags, optimizer, memory writes.
- **3:30:** recall + replan working; go/no-go on Firedrill and the benchmark.
- **3:45:** freeze.
