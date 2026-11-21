# Real-world held-out evaluation (public funeral General Price Lists)

Run (UTC): 2026-11-20 23:49:11. Pipeline call: `pipeline.extract.extract_quote_meta` on each GPL text (provenance header lines stripped), no tuning, one run.
Backend reported by sie_client across 209 calls: **sie** -> **real Superlinked SIE**. Models: fastino/GLiNER2.5-Decide, fastino/gliner2-large-v1. Calls that fell back to local after a remote error: **0**.
Sum of per-call reported latency: 222421 ms.
Document-level exceptions: none.

## Method

- 8 publicly posted GPLs (HTML pages and PDF text layers; see SOURCES.md for URL and capture date 2026-11-20). Each text was saved as captured (PDF via pypdf text layer, HTML via tag stripping and trimming of site navigation); ligatures, lost spaces and dot leaders were deliberately NOT repaired.
- 137 line items relevant to direct cremation were hand-labeled by reading the text (labels.json, with the verbatim evidence line per item). Labels were written before the pipeline was run on these files; the pipeline output was never consulted for labeling.
- Scoring is bench/run.py's `find`/`score` (imported): an item is *found* if a label's regex matches an extracted item's name (else its excerpt), preferring one whose amount_low equals the label; amount is compared on amount_low only (range high ends are stored in labels but not scored); price_type and category are exact matches. Accuracy denominators are all labeled items (a miss counts wrong). A found item with a wrong amount can still count as found (same as bench/run.py).
- Ranges are labeled price_type `estimated` with low/high, `from $X`/`$X+` as `starting_at`, 'Varies/Per Quote' as `unknown` with null amounts, 'Included ($0)' / 'No Fee Charged' as fixed 0 (project convention in bench/labels.json).
- 19 labels are category-arguable (transfer, refrigeration, alternative container, and two others); they follow the project convention (basic_fee for transfer/refrigeration/container). Category accuracy is reported with and without them.

## Overall

| Metric | Value |
|---|---|
| Labeled items | 137 |
| Found | 81.8% |
| Amount correct (of all labeled) | 76.6% |
| Amount correct (of found) | 93.8% |
| price_type correct | 72.3% |
| Category correct | 48.2% |
| Category correct excluding 19 arguable labels | 46.6% |
| All of found+amount+price_type+category | 41.6% |
| Items extracted in total | 461 |
| Extracted items not claimed by any label ('noise' upper bound) | 351 (76.1%) |

Caveat on noise: only direct-cremation-relevant items were labeled, so an unlabeled extracted item is not necessarily wrong (many are real, correctly priced GPL lines such as casket or viewing fees). Full lists are below; they were not audited item by item for correctness.

## Per document

| Doc | Source | Format | Labeled | Found | Amount | price_type | Category | All 4 | Extracted | Unlabeled | ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gpl_1 | www.toddmemorialchapel.com | HTML page (text extracted) | 13 | 13 | 12 | 11 | 7 | 6 | 68 | 56 | 36613 |
| gpl_2 | www.evergreenmemorialsacramento.com | HTML page (text extracted) | 18 | 10 | 8 | 7 | 7 | 3 | 32 | 22 | 18448 |
| gpl_3 | www.akesfamilyfuneralhome.com | HTML page, pipe-delimited table rows (te | 17 | 17 | 17 | 13 | 9 | 7 | 55 | 38 | 19669 |
| gpl_4 | www.pricefuneralchapel.com | HTML page, prose + packages + stacked na | 19 | 7 | 6 | 6 | 2 | 2 | 23 | 17 | 26068 |
| gpl_5 | cremationenterprises.com | PDF text layer via pypdf, ligature glyph | 19 | 18 | 17 | 18 | 11 | 11 | 85 | 67 | 38502 |
| gpl_6 | www.ohiocremation.org | PDF text layer via pypdf, dot-leader row | 17 | 16 | 16 | 15 | 7 | 6 | 86 | 70 | 33322 |
| gpl_7 | www.magallonfuneralhome.com | PDF text layer via pypdf, dash-leader ro | 19 | 18 | 16 | 17 | 13 | 13 | 66 | 48 | 27259 |
| gpl_8 | irp.cdn-website.com | PDF text layer via pypdf, words run toge | 15 | 13 | 13 | 12 | 10 | 9 | 46 | 33 | 22706 |

## Failure analysis (every miss or error)

Format: label id, what the text states (evidence), expected -> got (category/price_type/amount_low[-high]), likely cause. Causes are my reading of the evidence vs. the extracted item, not verified by instrumenting the pipeline.

- **gpl_1-04 WRONG label** Refrigeration in lieu of embalming: `A. Refrigeration in lieu of embalming - $250.00` expected basic_fee/fixed/250 -> got optional/fixed/250. Cause: category optional vs basic_fee (arguable label / project convention)
- **gpl_1-06 WRONG label** Direct cremation with alternative container, cardboard: `2. Direct cremation with alternative container, cardboard - $1,925.00` expected package/fixed/1925 -> got basic_fee/fixed/1925. Cause: category basic_fee vs package (classifier decision)
- **gpl_1-07 WRONG label** Direct cremation with container provided by purchaser: `3. Direct cremation with container provided by purchaser - $2,675.00` expected package/fixed/2675 -> got basic_fee/fixed/2675. Cause: category basic_fee vs package (classifier decision)
- **gpl_1-08 WRONG label** Direct cremation with casket selected from Todd's: `1. Direct cremation with casket selected from Todd's, in addition to the cost of the casket - $1,875.00` expected package/fixed/1875 -> got optional/fixed/1875. Cause: category optional vs package (classifier decision)
- **gpl_1-09 WRONG price_type+label** Direct cremations price range: `DIRECT CREMATIONS RANGE IN PRICE: from $1,875.00 to $2,675.00` expected package/estimated/1875-2675 -> got optional/starting_at/1875. Cause: price_type starting_at vs estimated: range or 'starting at/from/+' wording not mapped; category optional vs package (classifier decision)
- **gpl_1-11 WRONG label** Delivery van to local crematory (witness cremation): `B. To local crematory at designated time (Witness Cremation) - $200.00` expected optional/fixed/200 -> got cash_advance/fixed/200. Cause: category cash_advance vs optional (classifier decision)
- **gpl_1-13 WRONG amount+price_type** Crematory fees not included in direct cremation charge: `These charges DO NOT include viewing, funeral ceremony, crematory fees, county or state fees, or taxes.` expected cash_advance/unknown/- -> got cash_advance/fixed/200. Cause: different number picked (200); likely another price on the same/adjacent line or matched a different item with the same name; price_type fixed vs unknown: unknown/fixed handling of 'Varies'/'included'/0
- **gpl_2-02 WRONG amount** Transfer of the decedent to the funeral home: `B. TRANSFER OF THE DECEDENT TO THE FUNERAL HOME ... within 35 miles ... $485.00` expected basic_fee/fixed/485 -> got basic_fee/fixed/3.5. Cause: different number picked (3.5); likely another price on the same/adjacent line or matched a different item with the same name
- **gpl_2-04 WRONG amount+price_type** Crematory fee: `11. CREMATORY FEE $ 350.00` expected cash_advance/fixed/350 -> got cash_advance/unknown/-. Cause: amount dropped (None) although the text states a price; price_type unknown vs fixed: unknown/fixed handling of 'Varies'/'included'/0
- **gpl_2-05 MISSED** Witness cremation or expedite cremation service: `12. WITNESS CREMATION OR EXPEDITE CREMATION SERVICE $ 350.00` expected optional/fixed/350. Cause: an item with the right amount exists ('Dressing') but its name/excerpt does not match the label regex: naming/segmentation difference
- **gpl_2-06 MISSED** Certified death certificate (Sacramento County): `3. CERTIFIED DEATH CERTIFICATE (SACRAMENTO COUNTY) $ 26.00` expected cash_advance/fixed/26. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_2-07 MISSED** County of Sacramento filing fee for interment permit: `1. COUNTY OF SACRAMENTO FILING FEE FOR INTERMENT PERMIT $ 12.00` expected cash_advance/fixed/12. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_2-08 MISSED** Department of Consumer Affairs (DCA) fees: `22. DEPARTMENT OF CONSUMER AFFAIRS (DCA FEES.) $ 11.50` expected cash_advance/fixed/11.5. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_2-09 WRONG label** Direct cremation with container provided by purchaser: `1) Direct Cremation with container provided by purchaser $ 1,024.40` expected package/fixed/1024.4 -> got basic_fee/fixed/1024.4. Cause: category basic_fee vs package (classifier decision)
- **gpl_2-10 WRONG label** Direct cremation with Alternative Container I: `2) Direct Cremation with Alternative Container I $ 1,048.40` expected package/fixed/1048.4 -> got basic_fee/fixed/1048.4. Cause: category basic_fee vs package (classifier decision)
- **gpl_2-11 WRONG label** Direct cremation price range: `DIRECT CREMATION - $1,024.40 TO $13,365.30` expected package/estimated/1024.4-13365.3 -> got optional/estimated/1024.4-13365.3. Cause: category optional vs package (classifier decision)
- **gpl_2-13 WRONG price_type** Urns: `URNS - $24.00 TO $3,250.00` expected optional/estimated/24-3250 -> got optional/fixed/24. Cause: price_type fixed vs estimated: range or 'starting at/from/+' wording not mapped
- **gpl_2-14 WRONG price_type** Alternative containers offered for sale: `ALL ALTERNATIVE CONTAINERS OFFERED FOR SALE $ 24.00 TO $ 200.00` expected optional/estimated/24-200 -> got optional/fixed/24. Cause: price_type fixed vs estimated: range or 'starting at/from/+' wording not mapped
- **gpl_2-15 MISSED** Mailing of cremated remains (US Postal Service): `16. MAILING OF CREMATED REMAINS (US POSTAL SERVICE) $ 150.00` expected optional/fixed/150. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_2-16 MISSED** Delivery of cremated remains to residence: `13. DELIVERY OF CREMATED REMAINS TO RESIDENCE $ 50.00` expected optional/fixed/50. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_2-17 MISSED** Insurance processing fee: `20. INSURANCE PROCESSING FEE $ 225.00` expected optional/fixed/225. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_2-18 MISSED** Cremation (300 to 400 lbs): `8. CREMATION (300LBS TO 400LBS) Variable` expected cash_advance/unknown/-. Cause: unpriced item ('Varies'/'Per Quote'/'as selected'/'not included'); the pipeline only emits unknown items for the crematory fee and requirement sentences
- **gpl_3-04 WRONG price_type+label** Refrigeration, no embalming: `A. Refrigeration, no embalming (up to 6 days ...) | $650.00` expected basic_fee/fixed/650 -> got optional/estimated/650. Cause: price_type estimated vs fixed: range or 'starting at/from/+' wording not mapped; category optional vs basic_fee (arguable label / project convention)
- **gpl_3-05 WRONG label** Basic direct cremation incl. minimum alternative cardboard container: `A. Basic direct cremation including minimum alternative cardboard cremation container | $1,544.00` expected package/fixed/1544 -> got basic_fee/fixed/1544. Cause: category basic_fee vs package (classifier decision)
- **gpl_3-06 WRONG label** Basic direct cremation with casket from funeral home: `B. Basic direct cremation with a casket selected from our funeral home, add cost of casket selected | $1,619.00` expected package/fixed/1619 -> got optional/fixed/1619. Cause: category optional vs package (classifier decision)
- **gpl_3-07 WRONG label** Basic direct cremation with container provided by purchaser: `C. Basic direct cremation with container provided by the purchaser | $1,469.00` expected package/fixed/1469 -> got basic_fee/fixed/1469. Cause: category basic_fee vs package (classifier decision)
- **gpl_3-08 WRONG price_type+label** Direct cremation price range: `12. Direct Cremation Price Range From | $1,469.00 to $ 1,619.00` expected package/estimated/1469-1619 -> got optional/fixed/1469. Cause: price_type fixed vs estimated: range or 'starting at/from/+' wording not mapped; category optional vs package (classifier decision)
- **gpl_3-10 WRONG price_type** Alternative containers: `B. Alternative containers ... | $75.00 to $995.00` expected optional/estimated/75-995 -> got optional/fixed/75. Cause: price_type fixed vs estimated: range or 'starting at/from/+' wording not mapped
- **gpl_3-12 WRONG label** Family viewing and witnessing at the crematorium: `B. Family viewing and witnessing - at the crematorium ... additional | $495.00` expected optional/fixed/495 -> got cash_advance/fixed/495. Cause: category cash_advance vs optional (classifier decision)
- **gpl_3-15 WRONG price_type** Shipment of cremated remains (within USA): `B. Shipment of cremated remains (within U.S.A. via Registered Mail) | $125.00 to $225` expected optional/estimated/125-225 -> got optional/fixed/125. Cause: price_type fixed vs estimated: range or 'starting at/from/+' wording not mapped
- **gpl_3-16 WRONG label** Delivery of cremated remains to a local cemetery: `D. Delivery to a local cemetery ... | $105.00` expected optional/fixed/105 -> got cash_advance/fixed/105. Cause: category cash_advance vs optional (classifier decision)
- **gpl_3-17 WRONG label** Pacemaker removal and return to manufacturer: `B. Pacemaker removal and return to manufacturer | $195.00` expected optional/fixed/195 -> got basic_fee/fixed/195. Cause: category basic_fee vs optional (classifier decision)
- **gpl_4-01 WRONG amount+label** Direct Cremation package: `Direct Cremation $2,395 (package listing)` expected package/fixed/2395 -> got optional/fixed/1500. Cause: different number picked (1500); likely another price on the same/adjacent line or matched a different item with the same name; category optional vs package (classifier decision)
- **gpl_4-02 WRONG label** Direct cremation with alternative container provided by purchaser: `A direct cremation with an alternative container provided by the purchaser is $2,350.` expected package/fixed/2350 -> got basic_fee/fixed/2350. Cause: category basic_fee vs package (classifier decision)
- **gpl_4-03 WRONG price_type+label** Direct cremation with minimum cardboard container from funeral home: `A direct cremation with a minimum cardboard alternative container purchased from our funeral home is $2350.` expected package/fixed/2350 -> got basic_fee/starting_at/2350. Cause: price_type starting_at vs fixed: range or 'starting at/from/+' wording not mapped; category basic_fee vs package (classifier decision)
- **gpl_4-04 WRONG label** Direct cremation with hardboard/composite/wood container: `... hardboard, composite materials, or wood purchased from our funeral home ranges in price from $2,531 -$3,845.` expected package/estimated/2531-3845 -> got basic_fee/estimated/2531-3845. Cause: category basic_fee vs package (classifier decision)
- **gpl_4-05 WRONG label** Direct Cremation (infants and children, 5 years and under): `| Direct Cremation | $1,500.00 (table: 5 Years & Under)` expected package/fixed/1500 -> got optional/fixed/1500. Cause: category optional vs package (classifier decision)
- **gpl_4-06 MISSED** Basic Services of Funeral Director & Staff: `Basic Services of Funeral Director & Staff: $2,395.00` expected basic_fee/fixed/2395. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_4-08 MISSED** Basic transfer from place of death: `Basic Transfer from Place of Death (25 miles, M-F 9am - 4pm) $700.00` expected basic_fee/fixed/700. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_4-09 MISSED** Sheltering of decedent through refrigeration (per day): `Sheltering of Decedent through Refrigeration $75/day` expected basic_fee/fixed/75. Cause: an item with the right amount exists ('Paper') but its name/excerpt does not match the label regex: naming/segmentation difference
- **gpl_4-10 MISSED** Crematory fee (up to 299 lbs): `Crematory Fee (up to 299 lbs.) $318.50` expected cash_advance/fixed/318.5. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_4-11 MISSED** Crematory fee (300-399 lbs): `Crematory Fee (300 – 399 lbs.) $408.50` expected cash_advance/fixed/408.5. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_4-12 MISSED** Crematory fee (400 lbs or more): `Crematory Fee (400 lbs. or more) Per Quote` expected cash_advance/unknown/-. Cause: unpriced item ('Varies'/'Per Quote'/'as selected'/'not included'); the pipeline only emits unknown items for the crematory fee and requirement sentences
- **gpl_4-13 MISSED** Family witness of cremation: `Family Witness of Cremation $400.00` expected optional/fixed/400. Cause: an item with the right amount exists ('Or B) assignment of insurance policy benefits') but its name/excerpt does not match the label regex: naming/segmentation difference
- **gpl_4-14 MISSED** Delivery of cremated remains (within 25 miles): `Delivery of Cremated Remains (w/in 25 miles) $75.00` expected optional/fixed/75. Cause: an item with the right amount exists ('Paper') but its name/excerpt does not match the label regex: naming/segmentation difference
- **gpl_4-15 MISSED** Shipping and postage of cremains within USA: `Shipping & Postage of Cremains within USA $300.00` expected optional/fixed/300. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_4-16 MISSED** Transfer cremains into family provided urn: `Transfer Cremains into Family Provided Urn $200.00` expected optional/fixed/200. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_4-17 MISSED** Certified mailing of death certificates: `Certified Mailing of Death Certificates $95.00` expected optional/fixed/95. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_4-18 MISSED** Notarized cremation certificate: `Notarized Cremation Certificate $175.00` expected optional/fixed/175. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_5-02 WRONG label** Direct Cremation (range): `Direct Cremation $1,495 - $5,290` expected package/estimated/1495-5290 -> got optional/estimated/1495-5290. Cause: category optional vs package (classifier decision)
- **gpl_5-03 WRONG amount+label** Direct cremation with casket or alternative container provided by consumer: `- with combustible casket or alternative container provided by consumer $1,495` expected package/fixed/1495 -> got optional/fixed/2295. Cause: different number picked (2295); likely another price on the same/adjacent line or matched a different item with the same name; category optional vs package (classifier decision)
- **gpl_5-04 WRONG label** Direct cremation with alternative container purchased from funeral home: `- with alternative container purchased from funeral home $1,660` expected package/fixed/1660 -> got basic_fee/fixed/1660. Cause: category basic_fee vs package (classifier decision)
- **gpl_5-05 WRONG label** Direct cremation with combustible casket purchased from funeral home: `- with combustible casket purchased from funeral home (in addition to cost of casket selected) $1,495` expected package/fixed/1495 -> got optional/fixed/1495. Cause: category optional vs package (classifier decision)
- **gpl_5-12 WRONG label** Removal of pacemaker or other medical device: `Removal of Pacemaker, Battery Powered, or Other Medical Device $100` expected optional/fixed/100 -> got basic_fee/fixed/100. Cause: category basic_fee vs optional (classifier decision)
- **gpl_5-13 WRONG label** Fee for obtaining and sending death certificates: `Our Fee for Obtaining & Sending Death Certificates (one-time service fee ...) $50` expected cash_advance/fixed/50 -> got optional/fixed/50. Cause: category optional vs cash_advance (arguable label / project convention)
- **gpl_5-14 MISSED** State/county fee per death certificate: `State/County Fee per Certificate ... Varies by state/county` expected cash_advance/unknown/-. Cause: unpriced item ('Varies'/'Per Quote'/'as selected'/'not included'); the pipeline only emits unknown items for the crematory fee and requirement sentences
- **gpl_5-19 WRONG label** Transfer from residence or assisted living facility: `Transfer of Loved One from a Residence or Assisted Living Facility $165` expected optional/fixed/165 -> got basic_fee/fixed/165. Cause: category basic_fee vs optional (classifier decision)
- **gpl_6-02 WRONG label** Just a Simple Cremation: `"Just a Simple Cremation" ........$1,195` expected package/fixed/1195 -> got optional/fixed/1195. Cause: category optional vs package (classifier decision)
- **gpl_6-03 WRONG label** Simple Cremation with Final Goodbye: `Simple Cremation with Final Goodbye ........$1,470` expected package/fixed/1470 -> got optional/fixed/1470. Cause: category optional vs package (classifier decision)
- **gpl_6-04 WRONG label** Cremation with Memorial Service: `Cremation with Memorial Service ........$1,595` expected package/fixed/1595 -> got optional/fixed/1595. Cause: category optional vs package (classifier decision)
- **gpl_6-05 WRONG label** Direct - Simple Cremation (range): `Direct - Simple Cremation ........$1,195 - $ 2,995` expected package/estimated/1195-2995 -> got optional/estimated/1195-2995. Cause: category optional vs package (classifier decision)
- **gpl_6-06 WRONG label** Direct cremation with cremation container provided by purchaser: `Direct Cremation with Cremation Container for the remains provided by Purchaser ........$1,195` expected package/fixed/1195 -> got basic_fee/fixed/1195. Cause: category basic_fee vs package (classifier decision)
- **gpl_6-07 WRONG label** Direct cremation with alternative container (cardboard): `Direct Cremation with Alternative Container (cardboard) ........$1,195` expected package/fixed/1195 -> got basic_fee/fixed/1195. Cause: category basic_fee vs package (classifier decision)
- **gpl_6-08 WRONG label** Direct cremation with fiberboard cremation casket: `Direct Cremation with Fiberboard Cremation Casket ........$1,845` expected package/fixed/1845 -> got optional/fixed/1845. Cause: category optional vs package (classifier decision)
- **gpl_6-09 MISSED** Direct cremation with casket from casket price list: `Direct Cremation with Casket selected from Casket Price List ........as selected` expected package/unknown/-. Cause: unpriced item ('Varies'/'Per Quote'/'as selected'/'not included'); the pipeline only emits unknown items for the crematory fee and requirement sentences
- **gpl_6-10 WRONG label** Family witness of cremation (Mon-Fri): `Family Witness of Cremation at our Crematory (without viewing) up to 3 people ........Mon-Fri $275` expected optional/fixed/275 -> got cash_advance/fixed/275. Cause: category cash_advance vs optional (classifier decision)
- **gpl_6-13 WRONG label** Cremation container fiberboard alternative (OSHA required): `Cremation Container Fiberboard Alternative (OSHA required) ........$100` expected basic_fee/fixed/100 -> got stated_requirement/fixed/100. Cause: category stated_requirement vs basic_fee (arguable label / project convention)
- **gpl_6-15 WRONG price_type** Processing, packaging and mailing fee for cremated remains: `Processing, packaging and Mailing Fee for Cremated Remains ........$125+` expected optional/starting_at/125 -> got optional/fixed/125. Cause: price_type fixed vs starting_at: range or 'starting at/from/+' wording not mapped
- **gpl_7-03 WRONG amount+price_type+label** Refrigeration: `Refrigeration: ... (3 Day or Timeframe Required) - - - $375.00` expected basic_fee/fixed/375 -> got stated_requirement/unknown/-. Cause: amount dropped (None) although the text states a price; price_type unknown vs fixed: unknown/fixed handling of 'Varies'/'included'/0; category stated_requirement vs basic_fee (arguable label / project convention)
- **gpl_7-06 WRONG label** Direct cremations with alternate container: `DIRECT CREMATIONS with alternate container - - - $995.00` expected package/fixed/995 -> got basic_fee/fixed/995. Cause: category basic_fee vs package (classifier decision)
- **gpl_7-07 WRONG amount+label** Direct cremation with container provided by purchaser: `Direct Cremation with container provided by purchaser ... $995.00` expected package/fixed/995 -> got optional/fixed/1895. Cause: different number picked (1895); likely another price on the same/adjacent line or matched a different item with the same name; category optional vs package (classifier decision)
- **gpl_7-15 WRONG label** Cremation with memorial service: `CEMATION WITH MEMORIAL SERVICE - - - $1,995.00` expected package/fixed/1995 -> got optional/fixed/1995. Cause: category optional vs package (classifier decision)
- **gpl_7-16 MISSED** Pacemaker removal (no fee charged): `Pacemaker Removal (as required for cremation) - - - No Fee Charged` expected optional/fixed/0. Cause: no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)
- **gpl_7-19 WRONG label** Funeral ceremony with cremation: `FUNERAL CEREMONY WITH CREMATION - - - $3,795.00` expected package/fixed/3795 -> got optional/fixed/3795. Cause: category optional vs package (classifier decision)
- **gpl_8-03 WRONG label** Local transfer of the decedent into our care: `Localtransferofthedecedentintoourcare(upto275lbs,includesonestaffmember) $500.00` expected basic_fee/fixed/500 -> got optional/fixed/500. Cause: category optional vs basic_fee (arguable label / project convention)
- **gpl_8-05 WRONG label** Cremation fee, non-metal casket, up to 275 lbs: `CremationFee,Non-MetalCasket**upto275lbs** $395.00` expected cash_advance/fixed/395 -> got optional/fixed/395. Cause: category optional vs cash_advance (classifier decision)
- **gpl_8-08 WRONG price_type** Mailing of cremated remains (USPS Priority Express, starting at $300): `MailingofCrematedRemains(within the USA by USPS Priority Express, starting at $300.00) Varies` expected optional/starting_at/300 -> got optional/fixed/300. Cause: price_type fixed vs starting_at: range or 'starting at/from/+' wording not mapped
- **gpl_8-10 WRONG label** Direct cremation service: `DIRECT CREMATION SERVICE* $1590.00` expected package/fixed/1590 -> got optional/fixed/1590. Cause: category optional vs package (classifier decision)
- **gpl_8-13 MISSED** CA certified death certificate: `CACertifiedDeathCertificate–Costvariesbycountyofdeath Varies` expected cash_advance/unknown/-. Cause: unpriced item ('Varies'/'Per Quote'/'as selected'/'not included'); the pipeline only emits unknown items for the crematory fee and requirement sentences
- **gpl_8-14 MISSED** Coroner fee: `CoronerFee–Costvariesbycountyofdeath Varies` expected cash_advance/unknown/-. Cause: unpriced item ('Varies'/'Per Quote'/'as selected'/'not included'); the pipeline only emits unknown items for the crematory fee and requirement sentences

## Per-item results

| id | item | expected | got | found | amount | ptype | cat |
|---|---|---|---|---|---|---|---|
| gpl_1-01 | Basic services of funeral director, staff, and overhead | basic_fee/fixed/1950 | basic_fee/fixed/1950 | True | True | True | True |
| gpl_1-02 | Transfer of remains to funeral home (locally) | basic_fee/fixed/475 | basic_fee/fixed/475 | True | True | True | True |
| gpl_1-03 | Professional embalming | optional/fixed/600 | optional/fixed/600 | True | True | True | True |
| gpl_1-04 | Refrigeration in lieu of embalming | basic_fee/fixed/250 | optional/fixed/250 | True | True | True | False |
| gpl_1-05 | Alternative container for direct cremation | basic_fee/fixed/50 | basic_fee/fixed/50 | True | True | True | True |
| gpl_1-06 | Direct cremation with alternative container, cardboard | package/fixed/1925 | basic_fee/fixed/1925 | True | True | True | False |
| gpl_1-07 | Direct cremation with container provided by purchaser | package/fixed/2675 | basic_fee/fixed/2675 | True | True | True | False |
| gpl_1-08 | Direct cremation with casket selected from Todd's | package/fixed/1875 | optional/fixed/1875 | True | True | True | False |
| gpl_1-09 | Direct cremations price range | package/estimated/1875-2675 | optional/starting_at/1875 | True | True | False | False |
| gpl_1-10 | Cremation urns | optional/starting_at/150 | optional/starting_at/150 | True | True | True | True |
| gpl_1-11 | Delivery van to local crematory (witness cremation) | optional/fixed/200 | cash_advance/fixed/200 | True | True | True | False |
| gpl_1-12 | Packaging and shipping of cremated remains | optional/fixed/175 | optional/fixed/175 | True | True | True | True |
| gpl_1-13 | Crematory fees not included in direct cremation charge | cash_advance/unknown/- | cash_advance/fixed/200 | True | False | False | True |
| gpl_2-01 | Basic services of funeral director and staff | basic_fee/fixed/1225 | basic_fee/fixed/1225 | True | True | True | True |
| gpl_2-02 | Transfer of the decedent to the funeral home | basic_fee/fixed/485 | basic_fee/fixed/3.5 | True | False | True | True |
| gpl_2-03 | Embalming | optional/fixed/595 | optional/fixed/595 | True | True | True | True |
| gpl_2-04 | Crematory fee | cash_advance/fixed/350 | cash_advance/unknown/- | True | False | False | True |
| gpl_2-05 | Witness cremation or expedite cremation service | optional/fixed/350 | MISSED | False | - | - | - |
| gpl_2-06 | Certified death certificate (Sacramento County) | cash_advance/fixed/26 | MISSED | False | - | - | - |
| gpl_2-07 | County of Sacramento filing fee for interment permit | cash_advance/fixed/12 | MISSED | False | - | - | - |
| gpl_2-08 | Department of Consumer Affairs (DCA) fees | cash_advance/fixed/11.5 | MISSED | False | - | - | - |
| gpl_2-09 | Direct cremation with container provided by purchaser | package/fixed/1024.4 | basic_fee/fixed/1024.4 | True | True | True | False |
| gpl_2-10 | Direct cremation with Alternative Container I | package/fixed/1048.4 | basic_fee/fixed/1048.4 | True | True | True | False |
| gpl_2-11 | Direct cremation price range | package/estimated/1024.4-13365.3 | optional/estimated/1024.4-13365.3 | True | True | True | False |
| gpl_2-12 | Cremation with viewing package | package/fixed/2945 | package/fixed/2945 | True | True | True | True |
| gpl_2-13 | Urns | optional/estimated/24-3250 | optional/fixed/24 | True | True | False | True |
| gpl_2-14 | Alternative containers offered for sale | optional/estimated/24-200 | optional/fixed/24 | True | True | False | True |
| gpl_2-15 | Mailing of cremated remains (US Postal Service) | optional/fixed/150 | MISSED | False | - | - | - |
| gpl_2-16 | Delivery of cremated remains to residence | optional/fixed/50 | MISSED | False | - | - | - |
| gpl_2-17 | Insurance processing fee | optional/fixed/225 | MISSED | False | - | - | - |
| gpl_2-18 | Cremation (300 to 400 lbs) | cash_advance/unknown/- | MISSED | False | - | - | - |
| gpl_3-01 | Basic services of the funeral director and staff | basic_fee/fixed/1725 | basic_fee/fixed/1725 | True | True | True | True |
| gpl_3-02 | Embalming | optional/fixed/650 | optional/fixed/650 | True | True | True | True |
| gpl_3-03 | Transfer of deceased to funeral home | basic_fee/fixed/625 | basic_fee/fixed/625 | True | True | True | True |
| gpl_3-04 | Refrigeration, no embalming | basic_fee/fixed/650 | optional/estimated/650 | True | True | False | False |
| gpl_3-05 | Basic direct cremation incl. minimum alternative cardboard c | package/fixed/1544 | basic_fee/fixed/1544 | True | True | True | False |
| gpl_3-06 | Basic direct cremation with casket from funeral home | package/fixed/1619 | optional/fixed/1619 | True | True | True | False |
| gpl_3-07 | Basic direct cremation with container provided by purchaser | package/fixed/1469 | basic_fee/fixed/1469 | True | True | True | False |
| gpl_3-08 | Direct cremation price range | package/estimated/1469-1619 | optional/fixed/1469 | True | True | False | False |
| gpl_3-09 | Cremation urns | optional/estimated/20-2471 | optional/estimated/20-2471 | True | True | True | True |
| gpl_3-10 | Alternative containers | optional/estimated/75-995 | optional/fixed/75 | True | True | False | True |
| gpl_3-11 | Rush direct cremation and return (within 24 hours) | optional/fixed/310 | optional/fixed/310 | True | True | True | True |
| gpl_3-12 | Family viewing and witnessing at the crematorium | optional/fixed/495 | cash_advance/fixed/495 | True | True | True | False |
| gpl_3-13 | Private family identification viewing | optional/fixed/455 | optional/fixed/455 | True | True | True | True |
| gpl_3-14 | Scattering of cremated remains at sea | optional/fixed/150 | optional/fixed/150 | True | True | True | True |
| gpl_3-15 | Shipment of cremated remains (within USA) | optional/estimated/125-225 | optional/fixed/125 | True | True | False | True |
| gpl_3-16 | Delivery of cremated remains to a local cemetery | optional/fixed/105 | cash_advance/fixed/105 | True | True | True | False |
| gpl_3-17 | Pacemaker removal and return to manufacturer | optional/fixed/195 | basic_fee/fixed/195 | True | True | True | False |
| gpl_4-01 | Direct Cremation package | package/fixed/2395 | optional/fixed/1500 | True | False | True | False |
| gpl_4-02 | Direct cremation with alternative container provided by purc | package/fixed/2350 | basic_fee/fixed/2350 | True | True | True | False |
| gpl_4-03 | Direct cremation with minimum cardboard container from funer | package/fixed/2350 | basic_fee/starting_at/2350 | True | True | False | False |
| gpl_4-04 | Direct cremation with hardboard/composite/wood container | package/estimated/2531-3845 | basic_fee/estimated/2531-3845 | True | True | True | False |
| gpl_4-05 | Direct Cremation (infants and children, 5 years and under) | package/fixed/1500 | optional/fixed/1500 | True | True | True | False |
| gpl_4-06 | Basic Services of Funeral Director & Staff | basic_fee/fixed/2395 | MISSED | False | - | - | - |
| gpl_4-07 | Embalming | optional/fixed/1200 | optional/fixed/1200 | True | True | True | True |
| gpl_4-08 | Basic transfer from place of death | basic_fee/fixed/700 | MISSED | False | - | - | - |
| gpl_4-09 | Sheltering of decedent through refrigeration (per day) | basic_fee/fixed/75 | MISSED | False | - | - | - |
| gpl_4-10 | Crematory fee (up to 299 lbs) | cash_advance/fixed/318.5 | MISSED | False | - | - | - |
| gpl_4-11 | Crematory fee (300-399 lbs) | cash_advance/fixed/408.5 | MISSED | False | - | - | - |
| gpl_4-12 | Crematory fee (400 lbs or more) | cash_advance/unknown/- | MISSED | False | - | - | - |
| gpl_4-13 | Family witness of cremation | optional/fixed/400 | MISSED | False | - | - | - |
| gpl_4-14 | Delivery of cremated remains (within 25 miles) | optional/fixed/75 | MISSED | False | - | - | - |
| gpl_4-15 | Shipping and postage of cremains within USA | optional/fixed/300 | MISSED | False | - | - | - |
| gpl_4-16 | Transfer cremains into family provided urn | optional/fixed/200 | MISSED | False | - | - | - |
| gpl_4-17 | Certified mailing of death certificates | optional/fixed/95 | MISSED | False | - | - | - |
| gpl_4-18 | Notarized cremation certificate | optional/fixed/175 | MISSED | False | - | - | - |
| gpl_4-19 | Alternative containers (range) | optional/estimated/75-1495 | optional/estimated/75-1495 | True | True | True | True |
| gpl_5-01 | Basic Services of Funeral Director, Staff, and Overhead | basic_fee/fixed/1095 | basic_fee/fixed/1095 | True | True | True | True |
| gpl_5-02 | Direct Cremation (range) | package/estimated/1495-5290 | optional/estimated/1495-5290 | True | True | True | False |
| gpl_5-03 | Direct cremation with casket or alternative container provid | package/fixed/1495 | optional/fixed/2295 | True | False | True | False |
| gpl_5-04 | Direct cremation with alternative container purchased from f | package/fixed/1660 | basic_fee/fixed/1660 | True | True | True | False |
| gpl_5-05 | Direct cremation with combustible casket purchased from fune | package/fixed/1495 | optional/fixed/1495 | True | True | True | False |
| gpl_5-06 | Crematory fee | cash_advance/fixed/610 | cash_advance/fixed/610 | True | True | True | True |
| gpl_5-07 | Transfer of remains to the funeral home | basic_fee/fixed/495 | basic_fee/fixed/495 | True | True | True | True |
| gpl_5-08 | Basic cardboard alternative container | basic_fee/fixed/165 | basic_fee/fixed/165 | True | True | True | True |
| gpl_5-09 | Delivery of cremated remains | optional/fixed/165 | optional/fixed/165 | True | True | True | True |
| gpl_5-10 | USPS Priority Mail Express shipping of cremated remains | optional/fixed/165 | optional/fixed/165 | True | True | True | True |
| gpl_5-11 | Rush cremation | optional/fixed/825 | optional/fixed/825 | True | True | True | True |
| gpl_5-12 | Removal of pacemaker or other medical device | optional/fixed/100 | basic_fee/fixed/100 | True | True | True | False |
| gpl_5-13 | Fee for obtaining and sending death certificates | cash_advance/fixed/50 | optional/fixed/50 | True | True | True | False |
| gpl_5-14 | State/county fee per death certificate | cash_advance/unknown/- | MISSED | False | - | - | - |
| gpl_5-15 | Mailing of death certificates | optional/fixed/45 | optional/fixed/45 | True | True | True | True |
| gpl_5-16 | Cremated remains containers | optional/estimated/199-249 | optional/estimated/199-249 | True | True | True | True |
| gpl_5-17 | Temporary urn (included) | optional/fixed/0 | optional/fixed/0 | True | True | True | True |
| gpl_5-18 | Sheltering of remains (per day) | optional/fixed/65 | optional/fixed/65 | True | True | True | True |
| gpl_5-19 | Transfer from residence or assisted living facility | optional/fixed/165 | basic_fee/fixed/165 | True | True | True | False |
| gpl_6-01 | Basic Professional Services of Funeral Directors and Staff | basic_fee/fixed/1300 | basic_fee/fixed/1300 | True | True | True | True |
| gpl_6-02 | Just a Simple Cremation | package/fixed/1195 | optional/fixed/1195 | True | True | True | False |
| gpl_6-03 | Simple Cremation with Final Goodbye | package/fixed/1470 | optional/fixed/1470 | True | True | True | False |
| gpl_6-04 | Cremation with Memorial Service | package/fixed/1595 | optional/fixed/1595 | True | True | True | False |
| gpl_6-05 | Direct - Simple Cremation (range) | package/estimated/1195-2995 | optional/estimated/1195-2995 | True | True | True | False |
| gpl_6-06 | Direct cremation with cremation container provided by purcha | package/fixed/1195 | basic_fee/fixed/1195 | True | True | True | False |
| gpl_6-07 | Direct cremation with alternative container (cardboard) | package/fixed/1195 | basic_fee/fixed/1195 | True | True | True | False |
| gpl_6-08 | Direct cremation with fiberboard cremation casket | package/fixed/1845 | optional/fixed/1845 | True | True | True | False |
| gpl_6-09 | Direct cremation with casket from casket price list | package/unknown/- | MISSED | False | - | - | - |
| gpl_6-10 | Family witness of cremation (Mon-Fri) | optional/fixed/275 | cash_advance/fixed/275 | True | True | True | False |
| gpl_6-11 | Local transfer of remains to our facility | basic_fee/fixed/350 | basic_fee/fixed/350 | True | True | True | True |
| gpl_6-12 | Crematory fee | cash_advance/fixed/375 | cash_advance/fixed/375 | True | True | True | True |
| gpl_6-13 | Cremation container fiberboard alternative (OSHA required) | basic_fee/fixed/100 | stated_requirement/fixed/100 | True | True | True | False |
| gpl_6-14 | Embalming and professional care | optional/fixed/600 | optional/fixed/600 | True | True | True | True |
| gpl_6-15 | Processing, packaging and mailing fee for cremated remains | optional/starting_at/125 | optional/fixed/125 | True | True | False | True |
| gpl_6-16 | Expedite fee | optional/fixed/225 | optional/fixed/225 | True | True | True | True |
| gpl_6-17 | Oak rental casket for services followed by cremation (standa | optional/fixed/375 | optional/fixed/375 | True | True | True | True |
| gpl_7-01 | Professional services of the funeral director and staff | basic_fee/fixed/1955 | basic_fee/fixed/1955 | True | True | True | True |
| gpl_7-02 | Embalming | optional/fixed/595 | optional/fixed/595 | True | True | True | True |
| gpl_7-03 | Refrigeration | basic_fee/fixed/375 | stated_requirement/unknown/- | True | False | False | False |
| gpl_7-04 | Transfer of deceased from place of death to funeral home | basic_fee/fixed/450 | basic_fee/fixed/450 | True | True | True | True |
| gpl_7-05 | Alternative container | basic_fee/fixed/55 | basic_fee/fixed/55 | True | True | True | True |
| gpl_7-06 | Direct cremations with alternate container | package/fixed/995 | basic_fee/fixed/995 | True | True | True | False |
| gpl_7-07 | Direct cremation with container provided by purchaser | package/fixed/995 | optional/fixed/1895 | True | False | True | False |
| gpl_7-08 | Oversize fee for remains over 300 pounds | optional/fixed/450 | optional/fixed/450 | True | True | True | True |
| gpl_7-09 | Witness cremation fee | optional/fixed/350 | optional/fixed/350 | True | True | True | True |
| gpl_7-10 | Identification viewing only | optional/fixed/200 | optional/fixed/200 | True | True | True | True |
| gpl_7-11 | Certified death certificate | cash_advance/fixed/21 | cash_advance/fixed/21 | True | True | True | True |
| gpl_7-12 | Disposition permit (burial or cremation) | cash_advance/fixed/12 | cash_advance/fixed/12 | True | True | True | True |
| gpl_7-13 | Department of Consumer Affairs fee (cremation) | cash_advance/fixed/8.5 | cash_advance/fixed/8.5 | True | True | True | True |
| gpl_7-14 | Scattering cremated remains at sea | optional/fixed/150 | optional/fixed/150 | True | True | True | True |
| gpl_7-15 | Cremation with memorial service | package/fixed/1995 | optional/fixed/1995 | True | True | True | False |
| gpl_7-16 | Pacemaker removal (no fee charged) | optional/fixed/0 | MISSED | False | - | - | - |
| gpl_7-17 | Insurance claim processing fee | optional/fixed/500 | optional/fixed/500 | True | True | True | True |
| gpl_7-18 | Urns | optional/estimated/69-3100 | optional/estimated/69-3100 | True | True | True | True |
| gpl_7-19 | Funeral ceremony with cremation | package/fixed/3795 | optional/fixed/3795 | True | True | True | False |
| gpl_8-01 | Basic services of funeral director and staff | basic_fee/fixed/1195 | basic_fee/fixed/1195 | True | True | True | True |
| gpl_8-02 | Embalming | optional/fixed/600 | optional/fixed/600 | True | True | True | True |
| gpl_8-03 | Local transfer of the decedent into our care | basic_fee/fixed/500 | optional/fixed/500 | True | True | True | False |
| gpl_8-04 | Refrigeration or sheltering per day, starting 2nd day | basic_fee/fixed/50 | basic_fee/fixed/50 | True | True | True | True |
| gpl_8-05 | Cremation fee, non-metal casket, up to 275 lbs | cash_advance/fixed/395 | optional/fixed/395 | True | True | True | False |
| gpl_8-06 | Witness cremation 9:00am | optional/fixed/400 | optional/fixed/400 | True | True | True | True |
| gpl_8-07 | Cremation expediency | optional/fixed/200 | optional/fixed/200 | True | True | True | True |
| gpl_8-08 | Mailing of cremated remains (USPS Priority Express, starting | optional/starting_at/300 | optional/fixed/300 | True | True | False | True |
| gpl_8-09 | Unattended scattering of cremated remains at San Francisco | optional/fixed/300 | optional/fixed/300 | True | True | True | True |
| gpl_8-10 | Direct cremation service | package/fixed/1590 | optional/fixed/1590 | True | True | True | False |
| gpl_8-11 | CA disposition permit | cash_advance/fixed/12 | cash_advance/fixed/12 | True | True | True | True |
| gpl_8-12 | CA Department of Consumer Affairs fee | cash_advance/fixed/11.5 | cash_advance/fixed/11.5 | True | True | True | True |
| gpl_8-13 | CA certified death certificate | cash_advance/unknown/- | MISSED | False | - | - | - |
| gpl_8-14 | Coroner fee | cash_advance/unknown/- | MISSED | False | - | - | - |
| gpl_8-15 | Additional staff for transfer | optional/fixed/100 | optional/fixed/100 | True | True | True | True |

## Extracted but not claimed by any label

### gpl_1 (56 of 68)
- From Los Angeles, San Bernardino, Riverside or Orange County Coroner facilities, | cash_advance/fixed/75
- For Autopsy/Anatomical Gift Repair & Restoration | optional/fixed/250
- Dressing, cosmetology, preparation for viewing, and casketing | optional/fixed/200
- Hairdressing | optional/fixed/50
- Dressing only of un-embalmed remains | optional/fixed/150
- On site private autopsy or ceremonial bathing | optional/fixed/350
- Visitation room per 3-hour period | optional/fixed/250
- Viewing | optional/estimated/100
- Off-premises visitation prior to service, per 30-minute period | optional/fixed/50
- Saturday visitations, prior to 3:00 p.m., additional | optional/fixed/250
- To 4:00 p.m | optional/fixed/800
- Graveside or Cryptside Service or Witness Delivery | optional/fixed/350
- Evening Service | optional/fixed/1400
- Evening Service | optional/fixed/1325
- Or after 4:00 p.m., additional | optional/fixed/350
- Saturday services, additional | optional/fixed/500
- Sunday services, additional | optional/fixed/800
- HEARSE AND DRIVER, per use, locally | optional/fixed/475
- 7-passenger limousine, up to 4 hours | optional/estimated/525
- 12-passenger sprinter van, up to 4 hours | optional/estimated/725
- For greater distance (12 arrangements maximum) | optional/fixed/150
- For greater distance | optional/fixed/150
- Ontario International Airport | optional/fixed/350
- Los Angeles International Airport | optional/fixed/525
- MOTORCYCLE ESCORTS, 1 escort per 10 vehicles, minimum of 2 escorts required | stated_requirement/starting_at/250
- Escort | optional/fixed/75
- TRIBUTE VIDEOS | optional/fixed/250
- SCATTERING OF CREMATED REMAINS AT SEA (at our convenience) | optional/fixed/200
- PROCESSING AND FILING OF INSURANCE ASSIGNMENT, PER INSURANCE COMPANY | optional/fixed/200
- INTERNATIONAL SHIPMENT OF HUMAN REMAINS | optional/fixed/850
- TRADITIONAL CHAPEL OR CHURCH SERVICE | optional/fixed/4900
- GRAVESIDE OR CRYPTSIDE SERVICE | optional/fixed/4450
- EVENING SERVICE IN CHAPEL AND FOLLOWING DAY SERVICE IN CHAPEL OR CHURCH | optional/fixed/5250
- EVENING SERVICE AT CHURCH AND FOLLOWING DAY SERVICE AT CHURCH | optional/fixed/5725
- REGISTER BOOK AND ACKNOWLEDGMENT CARDS | optional/fixed/50
- PRINTED MATERIAL | optional/starting_at/50
- CRUCIFIX (each) | optional/fixed/25
- FLORAL CASKET SPRAYS | optional/starting_at/150
- PALLBEARER GLOVES (6 pair) | optional/fixed/25
- BURIAL CLOTHING | optional/fixed/250
- GRAVE MARKERS | optional/starting_at/825
- OUTER BURIAL CONTAINERS | optional/starting_at/925
- /or weekend services) | optional/fixed/200
- ADULT CASKETS | optional/starting_at/795
- INFANT/CHILD CASKETS | optional/fixed/150
- RENTAL CASKETS | optional/starting_at/1095
- SHIPPING AIRTRAY (required by airlines for shipping of casket) | stated_requirement/fixed/195
- COMBINATION AIRTRAY SHIPPING CONTAINER | basic_fee/fixed/295
- IMMEDIATE BURIALS RANGE IN PRICE | optional/starting_at/2350
- Casket | optional/fixed/2350
- Immediate burial with casket provided by purchaser | optional/fixed/3150
- FORWARDING OF REMAINS TO ANOTHER FUNERAL HOME | optional/fixed/2575
- With minimum shipping container | basic_fee/fixed/2870
- RECEIVING REMAINS FROM ANOTHER FUNERAL HOME | optional/fixed/1975
- Any items you did not specifically ask | stated_requirement/unknown/-
- You | stated_requirement/unknown/-

### gpl_2 (22 of 32)
- More than one person required, add | stated_requirement/fixed/250
- After 5:pm –Before 8:am, weekends and holidays | optional/fixed/90
- Dressing | optional/fixed/350
- Autopsy Repair | optional/fixed/350
- Refrigeration of the decedent (see below) | basic_fee/fixed/595
- (Non-autopsied) body, for up | optional/estimated/325
- Hairdressing and/or Makeup | optional/fixed/75
- Viewing | optional/fixed/250
- Mile | optional/fixed/3.5
- FORWARDING DECEDENT TO ANOTHER FUNERAL HOME | optional/fixed/1225
- RECEIVING DECEDENT FROM ANOTHER FUNERAL HOME | optional/fixed/1275
- ALL CASKETS REGULARLY OFFERED FOR SALE | optional/fixed/350
- URN VAULT | optional/fixed/175
- Casket | optional/fixed/1024.4
- Immediate burial with container provided by purchaser | basic_fee/fixed/1195
- Immediate burial with minimum cloth covered casket | optional/fixed/1545
- Immediate burial with casket as selected Range | optional/fixed/1545
- TRADITIONAL FUNERAL SERVICE Package | package/fixed/3900
- GRAVE OR CRYPTSIDE SERVICE Package | package/fixed/2995
- Any items you did not specifically ask | stated_requirement/unknown/-
- You | stated_requirement/unknown/-
- (Additional charge if more than one person | stated_requirement/unknown/-

### gpl_3 (38 of 55)
- A. Post autopsy, organ, tissue, bone harvest, additional | optional/estimated/450-1295
- C. Medical or ceremonial use of preparation room | optional/fixed/450
- B. Preparation of the body for viewing (Cosmetics, dressing, casketing and other | optional/fixed/350
- C. Sanitation & preparation, no embalming, ID view or non-view (handling, wrappi | optional/fixed/350
- D. Reconstruction, restoration cosmetics, when necessary and authorized, per hou | optional/fixed/195
- A. Visitation in the funeral home, (4 hour, weekday 4:00 P .M. – 8:00 P.M.) | optional/fixed/675
- B. Weekend or holiday visitation (Only) additional, each day | optional/fixed/1500
- C. Visitation in the funeral home, (2 hour, weekday 10:00 A.M. – 12:00 P.M.) | optional/fixed/337.5
- D. Visitation at church or other facility, (per 30 minute period) | optional/fixed/105
- A. Weekend or holiday ceremonies or memorial service, additional each ceremony o | optional/fixed/1500
- B. Chapel, church, graveside funeral ceremony or church, outside facility memori | optional/fixed/650
- C. Chapel memorial service | optional/fixed/650
- D. Evening service, rosary, wake or vigil | optional/fixed/395
- B. Casket coach (hearse) including driver, per use | optional/fixed/595
- Utility Vehicle | optional/fixed/335
- A. Adult caskets -A complete price list will be provided at the funeral home | optional/fixed/895
- D. Rental Casket Including Cremation Insert | optional/fixed/1295
- A. Memorial book | optional/fixed/37
- B. Standard printed memorial folders or prayer cards, each 50, (Special verse ty | optional/fixed/45
- C. Special printed memorial folders or prayer cards, each 100 (Custom with photo | optional/starting_at/298
- E. Casket crucifix | optional/fixed/29
- F. Outside Shipping container | basic_fee/fixed/395
- F. Memorial grave markers (Single, standard size, color and inscription) | optional/starting_at/385
- G. Floral arrangements | optional/starting_at/57.5
- Custom Video | optional/fixed/1
- 9. Forwarding of Remains to Another Funeral Home-Basic Ship-Out | optional/fixed/3135
- 10. Receiving Remains From Another Funeral Home-Basic Ship-In | optional/fixed/2458
- 11. Immediate Burial Price Range From | optional/fixed/4990
- A. Immediate burial with casket provided by purchaser | optional/fixed/3685
- B. Immediate burial with casket selected from our funeral home, add cost of cask | optional/fixed/3685
- C. Immediate burial including flat top, cloth covered alternative container | basic_fee/fixed/4999
- A. Saturday, Sunday, holiday – cremation or viewing, additional | optional/fixed/1500
- Crematory fee | cash_advance/fixed/350
- F. Identification viewing of an embalmed, casketed body including witness cremat | optional/fixed/295
- G. Care of embalmed remains (after 4 days, per day or portion thereof, including | optional/fixed/75
- Witness Placement | optional/fixed/295
- C. Processing and handling for placement per urn | optional/fixed/75
- Any item you did not specifically ask | stated_requirement/unknown/-

### gpl_4 (17 of 23)
- Casket | optional/fixed/3945
- Casket | optional/estimated/3095-14895
- Mile | optional/fixed/3.75
- Paper | optional/fixed/75
- Greater | optional/fixed/500
- Adult Caskets | optional/estimated/795-12500
- Complete Funeral Service | optional/fixed/3000
- Basic Funeral Service | optional/fixed/2400
- Visitation Privilege | optional/fixed/1900
- Minimum Service | optional/fixed/1900
- Forwarding of Decedent | optional/fixed/1900
- Immediate Burial | optional/fixed/1500
- Receiving of Decedent | optional/fixed/1500
- Or B) assignment of insurance policy benefits | optional/fixed/400
- Crematory fee | cash_advance/unknown/-
- Any items you did not specifically ask | stated_requirement/unknown/-
- You | stated_requirement/unknown/-

### gpl_5 (67 of 85)
- Casket prices for the service range | optional/estimated/1095-2695
- Discounted | optional/starting_at/5750
- Parting Stones | optional/fixed/1495
- Cremation Keepsakes / Sharing Urns | optional/estimated/29-49
- Cremation Jewelry — one complimentary per family Included | optional/fixed/0
- Additional Cremation Jewelry | optional/estimated/39-59
- Caskets | optional/estimated/165-2695
- Alternative Container | basic_fee/fixed/165
- Outer Burial Containers | optional/estimated/995-1095
- Over 300 lbs | optional/fixed/295
- Over 500 lbs | optional/fixed/295
- Embalming | optional/fixed/995
- Dressing | optional/fixed/200
- Autopsies, trauma, tissue donation, or other additional work) | optional/fixed/595
- Dressing | optional/fixed/295
- Crematory fee | cash_advance/fixed/895
- Use of Facilities and Staﬀ for Funeral Ceremony | optional/fixed/995
- Use of Facilities and Staﬀ for Memorial Service | optional/fixed/995
- Forwarding of Remains to Another Funeral Home | optional/fixed/3495
- Receiving Remains from Another Funeral Home | optional/fixed/2295
- Alternative container | basic_fee/fixed/1495
- Immediate Burial | optional/estimated/2295-4990
- With alternative container purchased from funeral home | basic_fee/fixed/2460
- Casket | optional/fixed/2295
- Memorial Tribute Video | optional/fixed/100
- 100 Memorial / Prayer Cards | optional/fixed/150
- Receiving/Sending Loved One To/From Airport | optional/fixed/825
- Death Certiﬁcate Corrections | cash_advance/fixed/95
- Transfer of Remains Outside 50 Mile Radi | basic_fee/fixed/2
- Notarization) | optional/fixed/295
- Ordered) | optional/fixed/50
- Temporary Cremation Urn (Plastic Box) Included | optional/fixed/0
- Silver Vine Urn | optional/fixed/195
- Purelight Urn | optional/fixed/209
- Crimson Bloom Urn | optional/fixed/229
- Midnight Gold Urn | optional/fixed/239
- Mother of Pearl Urn | optional/fixed/249
- Silver Stripe Keepsake Urn | optional/fixed/29
- Rose Gold Keepsake Urn | optional/fixed/39
- Black Keepsake Urn | optional/fixed/39
- Silver Tealight Keepsake Urn | optional/fixed/49
- Gold Tealight Keepsake Urn | optional/fixed/49
- Gold Heart Necklace | optional/fixed/39
- Black Cross Necklace | optional/fixed/39
- Turquoise Marble Necklace | optional/fixed/45
- Black Bullet Necklace | optional/fixed/45
- Silver Heart Bracelet | optional/fixed/49
- Gold Heart Bracelet | optional/fixed/49
- Silver Teardrop Necklace | optional/fixed/54
- Gold Cylinder Keychain | optional/fixed/59
- Basic Cardboard Cremation Container (Alternative Container) | basic_fee/fixed/165
- Vista Golden Oak / Vista Patriot | optional/fixed/795
- Novato Cremation Casket | optional/fixed/895
- Carrollton Golden Oak / Carrollton Cadet Blue | optional/fixed/1095
- Grey Doeskin Cremation Casket | optional/fixed/1195
- Miller / Fayette | optional/fixed/1200
- Paciﬁc Pine Cremation Casket | optional/fixed/1295
- Fiera Blue / Fiera Taupe | optional/fixed/1485
- Bancroft | optional/fixed/2095
- Homestead | optional/fixed/2295
- Quincy | optional/fixed/2695
- Outer Burial Container — Basic | basic_fee/fixed/995
- Outer Burial Container — American Standard Deluxe | basic_fee/fixed/1095
- Any items you did not speciﬁcally ask | stated_requirement/unknown/-
- That you buy a container | stated_requirement/unknown/-
- Aid of additional care team | stated_requirement/unknown/-
- You | stated_requirement/unknown/-

### gpl_6 (70 of 86)
- Funeral with Cremation | optional/fixed/38
- Viewing | optional/fixed/200
- Dressing, casketing and cosmetology | optional/fixed/150
- Post autopsy restoration care | optional/fixed/275
- Post organ donation charge | optional/fixed/295
- Restoration Charge | optional/fixed/275
- Refrigeration | basic_fee/fixed/75
- Regular weekday business hours with a three hour period | optional/fixed/350
- Visitation | optional/fixed/350
- Each additional hour of visitation or service | optional/fixed/150
- Supervising and directing Funeral | optional/fixed/350
- Funeral Director and staff | basic_fee/fixed/350
- Graveside or Committal Services with Funeral Director and Staff during regular w | basic_fee/fixed/250
- Memorial | optional/fixed/350
- Preparation of facial area for viewing | optional/fixed/275
- Mon-Fri | optional/fixed/275
- To your selected package | package/fixed/350
- Calling hours/visitation/memorial gathering on a Saturday or Sunday | optional/fixed/750
- Services on Holidays, should they be required add | stated_requirement/fixed/9
- In Home Arrangement Consultation by request | optional/fixed/275
- If Requires Second Person for Assistance Additional | stated_requirement/fixed/95
- Hearse / Funeral Coach | optional/fixed/350
- Alternative Vehicle – Van or Utility Vehicle | optional/fixed/100
- Local Use of Seven-Passenger Limousine (Additional) | optional/fixed/300
- Complete Traditional Service | optional/fixed/3295
- Graveside Service with Prior Day Visitation | optional/fixed/2995
- Immediate Burial | optional/fixed/2100
- Casket can be selected with costs begin | optional/fixed/895
- There will be an additional charge | optional/fixed/1
- Traditional Service | optional/fixed/500
- Church Funeral Plan | package/fixed/4390
- Green Burial | optional/fixed/2100
- Casket can be selected with costs begin | optional/fixed/1095
- Forwarding Remains to another Funeral Home | optional/fixed/1675
- Receiving Remains from another Funeral Home | optional/fixed/1350
- Anatomical Body Donation | optional/fixed/895
- Casket Selection | optional/estimated/1095-4995
- Container | basic_fee/estimated/1095-2550
- Cremation Urns | optional/fixed/25
- Urn Outer Burial Containers | optional/estimated/195-595
- Casket | optional/fixed/995
- Cherry Rental Casket for services followed by cremation | optional/fixed/1275
- Engraving of plates for urns begin | optional/fixed/35
- Memorial Register Book | optional/fixed/50
- Acknowledgment Cards (per 25) | optional/fixed/25
- Memorial Service Folders (up to 100 printed) | optional/estimated/75
- Additional Folders (per 25) | optional/fixed/20
- Prayer Cards (up to 64 printed) | optional/estimated/75
- Additional Prayer Cards (per 32) | optional/fixed/20
- Video Tribute (Single copy of up | optional/estimated/200
- Additional Video Copies | optional/fixed/25
- Laminated Obituary Book Marker | optional/fixed/5
- Temporary Grave Marker | optional/fixed/45
- Crucifix or Cross | optional/fixed/20
- Police Escort | optional/fixed/300
- Tent & Cemetery Equipment with Vault Installation | cash_advance/fixed/325
- Disaster Pouch | package/fixed/85
- Shipping Container | basic_fee/fixed/195
- Death certificate | cash_advance/fixed/150
- Mileage (loaded miles) per mile | optional/fixed/4
- Fee must be paid prior | stated_requirement/fixed/350
- Paperwork processing fee per page | optional/fixed/10
- Urn | optional/fixed/150
- Urn | optional/fixed/35
- Insurance Assignment of a verifiable policy | optional/fixed/150
- Any items you did not specifically ask | stated_requirement/unknown/-
- Embalming | stated_requirement/unknown/-
- You | stated_requirement/unknown/-
- Tax, and honorariums of any type | stated_requirement/unknown/-
- Payment | stated_requirement/unknown/-

### gpl_7 (48 of 66)
- Timeframe Required) | stated_requirement/fixed/375
- Bathing and Sanitation of remains | optional/fixed/150
- Dressing, Casketing, Cosmetology, & Hairdressing | optional/fixed/325
- Special Care for Autopsied Cases | optional/fixed/100
- Restorative Art (per hour) | optional/fixed/250
- *Evening from 5:00PM – 9:00PM | optional/fixed/495
- Use of Facilities and Staff | basic_fee/fixed/600
- Holidays (additional per day) 9:00AM – 5:00PM | optional/fixed/1000
- Ceremony | optional/fixed/495
- Use of Equipment and Staff for Committal/Graveside Service | basic_fee/fixed/495
- Use of Equipment and Staff for Committal/Graveside Service Outside San Diego Cou | cash_advance/fixed/695
- Memorial | optional/fixed/600
- Parties (Charged in Lieu of Basic Services Fee) | basic_fee/fixed/150
- Funeral Vehicle/Hearse | optional/fixed/300
- Flower/Utility Vehicle | optional/fixed/150
- Utility Vehicle | optional/fixed/150
- Adult Casket Price Range | optional/estimated/995-11995
- Youth Casket Price Range | optional/estimated/395-1995
- Air Tray | optional/fixed/200
- Combo Unit (Light Weight) | optional/fixed/200
- Rental Unit | optional/fixed/500
- CASKET ACCESSORIES Panel Inserts | optional/starting_at/150
- Memorial Book | optional/starting_at/45
- Custom Memorial Cards (Color/Photo) per 100 | optional/starting_at/130
- Crucifix | optional/fixed/25
- IMMEDIATE BURIAL | optional/fixed/2495
- FORWARDING OF REMAINS TO ANOTHER FUNERAL HOME (Out of State) | optional/fixed/2295
- RECEIVING REMAINS FROM ANOTHER FUNERAL HOME | optional/fixed/11595
- Crematory fee | cash_advance/fixed/995
- Fetal Death Certificate | cash_advance/fixed/18
- *Cross-file outside of San Diego County | cash_advance/fixed/125
- Clergy (Actual based on church fees) | cash_advance/estimated/150-600
- Escorts (for procession | optional/fixed/350
- Hairdresser (Custom Styles) | optional/starting_at/100
- Vinyl Encasement (Pouch) | optional/fixed/95
- TRADITIONAL SERVICE WITH GRAVESIDE SERVICE TO FOLLOW | optional/fixed/3795
- GRAVESIDE SERVICE WITH VISITATION | optional/fixed/2895
- DIRECT OR IMMEDIATE BURIAL | optional/fixed/2495
- Casket | optional/fixed/1895
- FORWARDING OF REMAINS TO ANOTHER FUNERAL HOME (Domestic Shipping) | optional/fixed/2295
- RECEIVING REMAINS FROM ANOTHER FUNERAL HOME | optional/fixed/1595
- SHIPOUT TO MEXICO WITH SERVICES IN OUR CHAPEL (only) | optional/fixed/6595
- Merchandise selected or cash advances | optional/fixed/1850
- Merchandise selected or cash advances | optional/fixed/2350
- 50% payment at time of arrangements with balance on | stated_requirement/unknown/-
- Any | stated_requirement/unknown/-
- You | stated_requirement/unknown/-
- SEALING CASKET | stated_requirement/unknown/-

### gpl_8 (33 of 46)
- Sanitationanddisinfectionofthenon-embalmed(non-autopsied)decedent | optional/fixed/200
- Placementofdecedentintoselectedcremationcontainerorcasket | optional/fixed/95
- Dressingofnon-embalmedremains | optional/fixed/150
- Dressingofembalmedremains | optional/fixed/95
- Autopsyrepair | optional/fixed/125
- Fingerprints | optional/fixed/25
- Pacemakerremoval&disposal | optional/fixed/45
- Transportationto/fromSacramentoInternationalAirport | optional/fixed/80
- LocaluseofHearse | optional/fixed/250
- LocaluseofServiceVehicle | optional/fixed/150
- AdultCaskets | optional/fixed/495
- Memorial | optional/estimated/395
- StaffandequipmentforCommittalCeremony (Monday – Friday, 9:00am-3:00pm) | optional/fixed/295
- AdditionalChargeforstaff,Weekends,Holidays,and/orEvenings | optional/fixed/250
- Max) | optional/fixed/275
- UseofOperatingRoomforPrivateAutopsy | optional/fixed/500
- StaffAssistwithcoordinatingmilitaryhonorsorCemeteryPlacement | optional/fixed/150
- PermitRefile (Cost of actual permit additional) | cash_advance/fixed/25
- DeathCertificateReorder (cost of Death Certificate(s) additional) | cash_advance/fixed/25
- InsuranceAssignmentProcessingFeew/C&JFinancial | optional/fixed/29
- AdditionalFeeforRemains**276lbsto375lbs** | optional/fixed/345
- AdditionalFeeforRemains**376lbsto475lbs** | optional/fixed/545
- AdditionalFeeforRemains**476lbsto575lbs** | optional/fixed/745
- WitnessCremation- 11:00amto1:00pm (Same stipulations as 9:00am Witness Cremation | optional/fixed/1000
- Notificationofcremationdateandtime | optional/fixed/200
- FORWARDING OF REMAINS TO ANOTHER FUNERAL HOME | optional/fixed/1495
- RECEIVING OF REMAINS FROM ANOTHER FUNERAL HOME | optional/fixed/650
- IMMEDIATE BURIAL | optional/fixed/1590
- IMMEDIATE BURIAL WITH FLAT TOP CASKET | optional/fixed/1790
- Removal,orweightofdeceased,thereisanadditional | basic_fee/fixed/100
- Crematory fee | cash_advance/unknown/-
- Any items you didn’t specifically ask | stated_requirement/unknown/-
- Once decedent | stated_requirement/unknown/-


## Top failure patterns (hand-written after the single run; re-running run.py regenerates everything above and drops this section)

Run used pipeline files with these sha1 prefixes (classify.py was being edited by another agent concurrently; this is the version that ran): classify.py dcd8a41fa1, extract.py 61dffe7b22, sie_client.py 0cae47ec30.

1. **Direct-cremation bundle prices are almost never categorized `package`: 1 of 33 found package labels correct** (13 came back basic_fee, 19 optional). The classifier treats "Direct cremation with alternative container ... $1,925" as a component, not a bundle. Largest single driver of the 48% category accuracy. Per-category category accuracy: package 1/34, cash_advance 9/21, basic_fee 17/25, optional 39/57.
2. **Price on its own line (stacked name / price layout) is not segmented: 20 of the 25 misses are in gpl_2 and gpl_4** (Evergreen and Price Funeral Chapel HTML, where the text is `NAME` newline `$ 350.00`). Crematory fees, death certificates, DCA fee, mailings, witness cremation were never emitted as priced items. gpl_4 found only 7 of 19 labels.
3. **Unpriced items ("Varies", "Per Quote", "as selected", "not included") are not emitted, and the crematory-unknown fallback can bind the wrong price.** 7 of the 25 misses are unknown-price labels (state/county certificate fee, coroner fee, 400+ lb crematory fee, casket-by-list direct cremation). gpl_1-13 (crematory fees "DO NOT" included) was emitted as a fixed $200 taken from the witness-cremation van line, and gpl_2-04 crematory fee $350 came back unknown with no amount. price_type unknown-vs-fixed errors among found items: 3.
4. **Ranges and "from/+" prices are collapsed to fixed or starting_at: 8 price_type errors** (5 estimated->fixed, 1 estimated->starting_at, 2 starting_at->fixed). Only the low end is scored here, so amount mostly survives.
5. **Wrong number / same-name collision between direct cremation and immediate burial lines and with fee-per-mile text**: gpl_5-03, gpl_7-07 and gpl_4-01 returned the immediate-burial or infant-table price ($2,295, $1,895, $1,500) for a direct cremation label; gpl_2-02 transfer took "$3.50 per mile" instead of $485. Part of this is label-regex ambiguity (labels for "provided by purchaser" also match the immediate burial lines; find() falls back to the first name match when no amount matches), so it overstates the pipeline error somewhat; gpl_4-01 and gpl_7-03 (refrigeration matched a CA-law requirement sentence) are of that kind.

Other observations. Layout damage was NOT the main problem: PDFs with ligatures (gpl_5, 18/19 found), dash leaders (gpl_7, 18/19) and dot leaders (gpl_6, 16/17) did well; gpl_8 (all spaces lost) found 13/15. Amount accuracy given found is 93.8%. Noise: 351 of 461 extracted items (76%) are not claimed by a label, but most are genuine non-cremation GPL lines (caskets, viewing, hearse, merchandise) that were intentionally not labeled; they were not audited individually, so precision is unmeasured rather than 76% wrong.
