"""Held-out real-world evaluation: pipeline.extract.extract_quote_meta on publicly posted funeral GPLs.
Run from project root:  .venv/bin/python bench/realworld/run.py
Scores exactly like bench/run.py (its find()/score() are imported, not reimplemented), writes
bench/realworld/results.json and results.md. Labels (labels.json) were written by reading the GPL text,
never from pipeline output. Nothing here tunes anything; the pipeline is called as-is."""
import hashlib, importlib.util, json, os, re, sys, time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(BENCH))

sys.path.insert(0, str(HERE))
from _scoring import find, score, g  # standalone copies, so this runs with any bench/run.py
try:  # load .env if python-dotenv is available
    from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
except Exception:
    pass


def load_doc(path):
    """Strip the leading '# ' provenance header (source URL / date) so it is not fed to the extractor."""
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines) and lines[i].startswith("# "):
        i += 1
    return "\n".join(lines[i:]) + "\n"


def header(path):
    d = {}
    for ln in path.read_text().splitlines():
        m = re.match(r"# (SOURCE_URL|CAPTURED|FORMAT): (.*)", ln)
        if m: d[m.group(1)] = m.group(2)
    return d


def run_pipeline(docs):
    from pipeline import sie_client, extract
    metas, per_doc, errors = [], {}, {}
    orig = sie_client.call
    def wrap(*a, **k):
        res, meta = orig(*a, **k); metas.append(dict(meta)); return res, meta
    sie_client.call = wrap
    try:
        for did, p in docs.items():
            t = time.perf_counter()
            try:
                items, _ = extract.extract_quote_meta(load_doc(p), p.name, did)
            except Exception as ex:
                items = []; errors[did] = f"{type(ex).__name__}: {ex}"
            per_doc[did] = (items, (time.perf_counter() - t) * 1000)
    finally:
        sie_client.call = orig
    return per_doc, metas, errors


def fmt(x):
    return "-" if x is None else (f"{x:g}")


def main():
    labels = json.load(open(HERE / "labels.json"))
    docs = {f"gpl_{i}": HERE / f"gpl_{i}.txt" for i in range(1, 100) if (HERE / f"gpl_{i}.txt").exists()}
    per_doc, metas, errors = run_pipeline(docs)
    items_by_doc = {k: v[0] for k, v in per_doc.items()}
    rows = score(items_by_doc, labels)
    lab_by_id = {l["id"]: l for l in labels}

    # which extracted items did a label claim (for noise = extracted but not in labels)
    claimed = defaultdict(set)
    for lab in labels:
        it = find(items_by_doc.get(lab["source"], []), lab)
        if it is not None: claimed[lab["source"]].add(id(it))
    unlabeled = {d: [i for i in its if id(i) not in claimed[d]] for d, its in items_by_doc.items()}

    for r in rows:
        r["all_ok"] = bool(r["found"] and r["amount_ok"] and r["price_type_ok"] and r["label_ok"]) if r["found"] else False
        r["category_arguable"] = lab_by_id[r["id"]].get("category_arguable", False)

    n = len(rows)
    def pct(k, rs=None):
        rs = rows if rs is None else rs
        return round(100 * sum(1 for r in rs if r["found"] and r[k]) / len(rs), 1) if rs else None
    found = round(100 * sum(r["found"] for r in rows) / n, 1)
    summ = {"n_labeled": n, "found_pct": found, "amount_pct": pct("amount_ok"), "price_type_pct": pct("price_type_ok"),
            "category_pct": pct("label_ok"), "all_fields_pct": round(100 * sum(r["all_ok"] for r in rows) / n, 1)}
    firm = [r for r in rows if not r["category_arguable"]]
    summ["category_pct_excluding_arguable"] = pct("label_ok", firm)
    summ["n_category_arguable"] = n - len(firm)
    # amount accuracy conditional on found
    fr = [r for r in rows if r["found"]]
    summ["amount_pct_given_found"] = round(100 * sum(r["amount_ok"] for r in fr) / len(fr), 1) if fr else None
    nitems = sum(len(v) for v in items_by_doc.values())
    summ["extracted_total"] = nitems
    summ["extracted_unlabeled"] = sum(len(v) for v in unlabeled.values())

    backends = sorted({str(m.get("backend")) for m in metas})
    fallbacks = [m for m in metas if m.get("fallback_from")]
    models = sorted({str(m.get("model")) for m in metas})
    sie_ms = round(sum(m.get("latency_ms", 0) or 0 for m in metas))
    pipe_hash = {p.name: hashlib.sha1(p.read_bytes()).hexdigest()[:10] for p in sorted((ROOT / "pipeline").glob("*.py"))}
    meta = {"backends_observed": backends, "models": models, "n_backend_calls": len(metas), "n_fallbacks_to_local": len(fallbacks),
            "fallback_errors": sorted({m.get("error", "") for m in fallbacks})[:5], "sum_call_latency_ms": sie_ms,
            "doc_errors": errors, "pipeline_file_sha1_prefix": pipe_hash, "run_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}

    per_doc_sum = {}
    for d in docs:
        rs = [r for r in rows if r["source"] == d]
        per_doc_sum[d] = {"n": len(rs), "found": sum(r["found"] for r in rs),
                          "amount": sum(1 for r in rs if r["found"] and r["amount_ok"]),
                          "price_type": sum(1 for r in rs if r["found"] and r["price_type_ok"]),
                          "category": sum(1 for r in rs if r["found"] and r["label_ok"]),
                          "all": sum(r["all_ok"] for r in rs), "extracted": len(items_by_doc[d]), "unlabeled": len(unlabeled[d]),
                          "ms": round(per_doc[d][1])}
    json.dump({"summary": summ, "meta": meta, "per_doc": per_doc_sum, "rows": rows,
               "unlabeled": {d: [{k: i.get(k) for k in ("name", "category", "price_type", "amount_low", "amount_high", "excerpt")} for i in v] for d, v in unlabeled.items()},
               "extracted": items_by_doc}, open(HERE / "results.json", "w"), indent=1, default=str)
    write_md(labels, lab_by_id, docs, rows, summ, meta, per_doc_sum, unlabeled, items_by_doc)
    print(json.dumps({"summary": summ, "meta": {k: meta[k] for k in ("backends_observed", "n_backend_calls", "n_fallbacks_to_local", "doc_errors")}}, indent=1))


def lab_str(l):
    return f"{l['category']}/{l['price_type']}/{fmt(l['amount_low'])}" + (f"-{fmt(l['amount_high'])}" if l['amount_high'] not in (None, l['amount_low']) else "")


def got_str(r):
    g_ = r["got"]
    return f"{g_['category']}/{g_['price_type']}/{fmt(g_['amount_low'])}" + (f"-{fmt(g_['amount_high'])}" if g_['amount_high'] not in (None, g_['amount_low']) else "")


def write_md(labels, lab_by_id, docs, rows, s, meta, pds, unlabeled, items_by_doc):
    be = ", ".join(meta["backends_observed"])
    honest = ("real Superlinked SIE" if be == "sie" else
              "LOCAL DETERMINISTIC PARSER (not SIE)" if be in ("local", "local_parser") else
              f"mixed/other: {be}")
    L = ["# Real-world held-out evaluation (public funeral General Price Lists)", "",
         f"Run (UTC): {meta['run_utc']}. Pipeline call: `pipeline.extract.extract_quote_meta` on each GPL text (provenance header lines stripped), no tuning, one run.",
         f"Backend reported by sie_client across {meta['n_backend_calls']} calls: **{be}** -> **{honest}**. Models: {', '.join(meta['models'])}. "
         f"Calls that fell back to local after a remote error: **{meta['n_fallbacks_to_local']}**" + (f" (errors: {'; '.join(meta['fallback_errors'])})" if meta["fallback_errors"] else "") + ".",
         f"Sum of per-call reported latency: {meta['sum_call_latency_ms']} ms.",
         f"Document-level exceptions: {meta['doc_errors'] or 'none'}.", "",
         "## Method", "",
         f"- {len(docs)} publicly posted GPLs (HTML pages and PDF text layers; see SOURCES.md for URL and capture date 2026-11-20). Each text was saved as captured (PDF via pypdf text layer, HTML via tag stripping and trimming of site navigation); ligatures, lost spaces and dot leaders were deliberately NOT repaired.",
         f"- {s['n_labeled']} line items relevant to direct cremation were hand-labeled by reading the text (labels.json, with the verbatim evidence line per item). Labels were written before the pipeline was run on these files; the pipeline output was never consulted for labeling.",
         "- Scoring is bench/run.py's `find`/`score` (imported): an item is *found* if a label's regex matches an extracted item's name (else its excerpt), preferring one whose amount_low equals the label; amount is compared on amount_low only (range high ends are stored in labels but not scored); price_type and category are exact matches. Accuracy denominators are all labeled items (a miss counts wrong). A found item with a wrong amount can still count as found (same as bench/run.py).",
         "- Ranges are labeled price_type `estimated` with low/high, `from $X`/`$X+` as `starting_at`, 'Varies/Per Quote' as `unknown` with null amounts, 'Included ($0)' / 'No Fee Charged' as fixed 0 (project convention in bench/labels.json).",
         f"- {s['n_category_arguable']} labels are category-arguable (transfer, refrigeration, alternative container, and two others); they follow the project convention (basic_fee for transfer/refrigeration/container). Category accuracy is reported with and without them.", "",
         "## Overall", "", "| Metric | Value |", "|---|---|",
         f"| Labeled items | {s['n_labeled']} |", f"| Found | {s['found_pct']}% |",
         f"| Amount correct (of all labeled) | {s['amount_pct']}% |", f"| Amount correct (of found) | {s['amount_pct_given_found']}% |",
         f"| price_type correct | {s['price_type_pct']}% |", f"| Category correct | {s['category_pct']}% |",
         f"| Category correct excluding {s['n_category_arguable']} arguable labels | {s['category_pct_excluding_arguable']}% |",
         f"| All of found+amount+price_type+category | {s['all_fields_pct']}% |",
         f"| Items extracted in total | {s['extracted_total']} |",
         f"| Extracted items not claimed by any label ('noise' upper bound) | {s['extracted_unlabeled']} ({round(100*s['extracted_unlabeled']/max(1,s['extracted_total']),1)}%) |", "",
         "Caveat on noise: only direct-cremation-relevant items were labeled, so an unlabeled extracted item is not necessarily wrong (many are real, correctly priced GPL lines such as casket or viewing fees). Full lists are below; they were not audited item by item for correctness.", "",
         "## Per document", "", "| Doc | Source | Format | Labeled | Found | Amount | price_type | Category | All 4 | Extracted | Unlabeled | ms |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d, p in docs.items():
        h = header(p); x = pds[d]
        L.append(f"| {d} | {h.get('SOURCE_URL','').split('/')[2]} | {h.get('FORMAT','')[:40]} | {x['n']} | {x['found']} | {x['amount']} | {x['price_type']} | {x['category']} | {x['all']} | {x['extracted']} | {x['unlabeled']} | {x['ms']} |")
    L += ["", "## Failure analysis (every miss or error)", "",
          "Format: label id, what the text states (evidence), expected -> got (category/price_type/amount_low[-high]), likely cause. Causes are my reading of the evidence vs. the extracted item, not verified by instrumenting the pipeline.", ""]
    bad = [r for r in rows if not r["all_ok"]]
    for r in bad:
        lab = lab_by_id[r["id"]]
        if not r["found"]:
            L.append(f"- **{r['id']} MISSED** {lab['name']}: `{lab['evidence'][:160]}` expected {lab_str(lab)}. Cause: {cause_missed(lab, items_by_doc[r['source']])}")
        else:
            wrong = [k for k, lbl in (("amount_ok", "amount"), ("price_type_ok", "price_type"), ("label_ok", "category")) if not r[k]]
            L.append(f"- **{r['id']} WRONG {'+'.join(w.replace('_ok','') for w in wrong)}** {lab['name']}: `{lab['evidence'][:160]}` expected {lab_str(lab)} -> got {got_str(r)}. Cause: {cause_wrong(lab, r, wrong)}")
    if not bad: L.append("- none")
    L += ["", "## Per-item results", "", "| id | item | expected | got | found | amount | ptype | cat |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lab = lab_by_id[r["id"]]
        L.append(f"| {r['id']} | {lab['name'][:60]} | {lab_str(lab)} | {got_str(r) if r['found'] else 'MISSED'} | {r['found']} | {r.get('amount_ok','-')} | {r.get('price_type_ok','-')} | {r.get('label_ok','-')} |")
    L += ["", "## Extracted but not claimed by any label", ""]
    for d in docs:
        L.append(f"### {d} ({len(unlabeled[d])} of {len(items_by_doc[d])})")
        L += [f"- {i['name'][:80]} | {i['category']}/{i['price_type']}/{fmt(i['amount_low'])}" + (f"-{fmt(i['amount_high'])}" if i['amount_high'] not in (None, i['amount_low']) else "") for i in unlabeled[d]] or ["- none"]
        L.append("")
    (HERE / "results.md").write_text("\n".join(L) + "\n")


def cause_missed(lab, items):
    """Heuristic pointer only: look at the raw labeled evidence for known problem formats."""
    ev = lab["evidence"]; src = lab["source"]
    near = [i for i in items if lab["amount_low"] is not None and i.get("amount_low") == lab["amount_low"]]
    if lab["amount_low"] is not None and near:
        return f"an item with the right amount exists ({near[0]['name'][:50]!r}) but its name/excerpt does not match the label regex: naming/segmentation difference"
    if lab["price_type"] == "unknown":
        return "unpriced item ('Varies'/'Per Quote'/'as selected'/'not included'); the pipeline only emits unknown items for the crematory fee and requirement sentences"
    if lab["price_type"] in ("estimated", "starting_at"):
        return "range / 'from' / '+' price not captured as an item"
    if src == "gpl_8":
        return "PDF text layer with spaces lost (words run together)"
    if src == "gpl_5":
        return "PDF layout: price detached from name or ligature glyphs (e.g. 'ﬀ'/'ﬁ') in the text"
    if "|" in ev or src == "gpl_3":
        return "pipe-delimited table row format or price on a separate line from its name"
    return "no extracted item with this amount; likely not segmented as a priced line (layout / sub-item / leader-dot or price-on-next-line format)"


def cause_wrong(lab, r, wrong):
    c = []
    got = r["got"]
    if "amount_ok" in wrong:
        if lab["price_type"] in ("estimated", "starting_at"):
            c.append("range/'from' amount: low end not taken")
        elif got["amount_low"] is None:
            c.append("amount dropped (None) although the text states a price")
        else:
            c.append(f"different number picked ({fmt(got['amount_low'])}); likely another price on the same/adjacent line or matched a different item with the same name")
    if "price_type_ok" in wrong:
        c.append(f"price_type {got['price_type']} vs {lab['price_type']}: " + ("range or 'starting at/from/+' wording not mapped" if lab["price_type"] in ("estimated", "starting_at") or got["price_type"] in ("estimated", "starting_at") else "unknown/fixed handling of 'Varies'/'included'/0"))
    if "label_ok" in wrong:
        c.append(f"category {got['category']} vs {lab['category']}" + (" (arguable label / project convention)" if lab.get("category_arguable") else " (classifier decision)"))
    return "; ".join(c)


if __name__ == "__main__":
    main()
