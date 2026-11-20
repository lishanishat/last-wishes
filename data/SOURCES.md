# Data sources

All provider names, people, emails and addresses in the fictional files are invented
for the demo. Seed documents are **inputs** to the pipeline, not scripted outputs.

| File | Real or fictional | What it is | Source ID |
|---|---|---|---|
| `wishes_linda.txt` | Fictional | Linda's (78) recorded note, verbatim | W-NOTE-1 |
| `confirmation_daughter.txt` | Fictional | Daughter Maya confirms wishes + ~$4,000 budget | W-CONF-1 |
| `quote_A.txt` | Fictional (Harborview Cremation Services) | Table format; low headline total; crematory charges "to be confirmed" (no price) | — |
| `quote_B.txt` | Fictional (Cedar Grove Funeral & Cremation) | Prose letter; complete itemized direct cremation | — |
| `quote_C.txt` | Fictional (Willowbrook Memorial Chapel) | Bullet list; "Celebration Package" with viewing/embalming/flowers + casket statement | — |
| `reply_A_v2.txt` | Fictional | Provider A email reply: crematory fee $395, refrigeration $150 → $195 | — |
| `reply_A_alt.txt` | Fictional | Same facts as `reply_A_v2.txt`, different wording/format (Firedrill scenario 3) | — |
| `ftc_reference.txt` | **Real** (paraphrased) | FTC consumer Funeral Rule guidance: alternative container, itemized prices/GPL, choosing only what you want / no false "required" claims, packages | FTC-1 … FTC-4 |
| `real_gpl.pdf` | **Real** (Menlo Park Funeral Home and Cremation Services, FD #2060) | Public seven-page General Price List; extraction test only | [Provider PDF](https://cdn.f1connect.net/cdn/15678M-Xj0/gpl/Menlo%20Park%20Funeral%20and%20Cremation%20Services%20GPL.pdf) |

## Wish IDs

| ID | Wish | Source |
|---|---|---|
| W1 | Cremation | W-NOTE-1, confirmed W-CONF-1 |
| W2 | No public viewing | W-NOTE-1, confirmed W-CONF-1 |
| W3 | Avoid unnecessary extras | W-NOTE-1, confirmed W-CONF-1 |
| W4 | Working budget about $4,000 | W-CONF-1 |

## FTC reference

- URLs: https://consumer.ftc.gov/articles/ftc-funeral-rule , https://consumer.ftc.gov/articles/shopping-funeral-services
- Checked against both pages on 2026-11-20 (the pages carry a July 2012 date). All four entries now use only claims the pages make, with short direct quotes marked.
- Note: the page says cremation providers must offer alternative containers ("cremations", not only "direct cremation"), and that no state or local law requires a casket for cremation.

## Real public price list

- File: `data/real_gpl.pdf`
- Source URL: https://cdn.f1connect.net/cdn/15678M-Xj0/gpl/Menlo%20Park%20Funeral%20and%20Cremation%20Services%20GPL.pdf
- Capture date: 2026-11-20
- Printed effective date: March 8, 2026 (as shown in the document)
- Use: extraction test only; never mixed with the fictional traps.
