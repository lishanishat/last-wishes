# SIE vs general LLM on 13 hand-labelled quote lines

Method: Each system saw the identical, source-verified line independently. SIE used the app's extract + classify pipeline (including code price parsing and explicit optional-service normalization); the general comparator was Qwen3.8 27B chat via the same hosted SIE account. No gold labels were in either prompt. All 13 cases, including errors, are below.

| System | Price field accuracy (type, low, high) | Category accuracy | Total wall time | Estimated API cost |
|---|---:|---:|---:|---:|
| SIE pipeline | 36/39 | 13/13 | 6452 ms | $0.000828 |
| Qwen chat | 39/39 | 11/13 | 16578 ms | $0.001948 |

Cost method: approximate SIE tokens as input characters / 4 including label/question text, then apply [Superlinked's November 2026 list prices](https://superlinked.com/models) for GLiNER2 large ($0.186/M) and Decide ($0.28/M). Chat cost uses the API's prompt/completion token counts and the listed Qwen3.8 27B rates ($0.25/M input, $2.75/M output). These are estimates, not billed USD; SIE's per-call schema overhead and tokenizer may differ. Wall time includes network and any model startup.

| Case (source) | Gold: category; type; low–high | SIE | Qwen chat | SIE ms | Chat ms |
|---|---|---|---|---:|---:|
| A-basic (quote_A.txt) | basic_fee; fixed; 895–895 | basic_fee; fixed; 895.0–895.0 | basic_fee; fixed; 895.0–895.0 | 951 | 1216 |
| A-unresolved (quote_A.txt) | basic_fee; unknown; None–None | basic_fee; unknown; None–None | optional; unknown; None–None | 521 | 1152 |
| B-crematory (quote_B.txt) | basic_fee; fixed; 350–350 | basic_fee; fixed; 350.0–350.0 | basic_fee; fixed; 350.0–350.0 | 439 | 1246 |
| B-container (quote_B.txt) | basic_fee; fixed; 95–95 | basic_fee; fixed; 95.0–95.0 | optional; fixed; 95.0–95.0 | 556 | 1355 |
| C-embalming (quote_C.txt) | optional; fixed; 795–795 | optional; fixed; 795.0–795.0 | optional; fixed; 795–795 | 486 | 1112 |
| C-viewing (quote_C.txt) | optional; fixed; 650–650 | optional; fixed; 650.0–650.0 | optional; fixed; 650.0–650.0 | 465 | 1459 |
| C-flowers (quote_C.txt) | optional; starting_at; 350–None | optional; starting_at; 350.0–None | optional; starting_at; 350–None | 444 | 1235 |
| C-casket (quote_C.txt) | optional; fixed; 1895–1895 | optional; fixed; 1895.0–1895.0 | optional; fixed; 1895.0–1895.0 | 391 | 1494 |
| C-certificates (quote_C.txt) | cash_advance; estimated; 48–96 | cash_advance; fixed; 24.0–24.0 | cash_advance; estimated; 48–96 | 443 | 1221 |
| C-package (quote_C.txt) | package; fixed; 6495–6495 | package; fixed; 6495.0–6495.0 | package; fixed; 6495.0–6495.0 | 422 | 1468 |
| C-requirement (quote_C.txt) | stated_requirement; unknown; None–None | stated_requirement; unknown; None–None | stated_requirement; unknown; None–None | 495 | 1068 |
| GPL-basic (real_gpl.pdf) | basic_fee; fixed; 2195–2195 | basic_fee; fixed; 2195.0–2195.0 | basic_fee; fixed; 2195–2195 | 378 | 1192 |
| GPL-crematory (real_gpl.pdf) | basic_fee; fixed; 695–695 | basic_fee; fixed; 695.0–695.0 | basic_fee; fixed; 695–695 | 461 | 1360 |

Raw predictions, timing, and usage metadata are in `results.json`. The public GPL lines are extraction tests only and never affect the fictional family plan.
