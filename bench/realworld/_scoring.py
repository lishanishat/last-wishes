"""Scoring helpers (copied from the benchmark script so this folder runs standalone)."""
import re

def g(it, k):
    return it.get(k) if isinstance(it, dict) else getattr(it, k, None)

def find(item_list, lab):
    rx = re.compile(lab["match"], re.I)
    c = [i for i in item_list if rx.search(g(i, "name") or "")] or [i for i in item_list if rx.search(g(i, "excerpt") or "")]
    ok = [lab["amount_low"]] + lab["alt_amounts"]
    for i in c:
        if g(i, "amount_low") in ok: return i
    return c[0] if c else None

def score(per_doc_items, labels, cat_key="category"):
    rows = []
    for lab in labels:
        it = find(per_doc_items.get(lab["source"], []), lab)
        r = {"id": lab["id"], "source": lab["source"], "name": lab["name"], "found": it is not None}
        if it is not None:
            lo, hi = g(it, "amount_low"), g(it, "amount_high")
            oklo = [lab["amount_low"]] + lab["alt_amounts"]
            r["amount_ok"] = (lo is None and lab["amount_low"] is None) or (lo is not None and any(o is not None and abs(lo-o) < 0.005 for o in oklo))
            r["price_type_ok"] = g(it, "price_type") == lab["price_type"]
            r["label_ok"] = g(it, cat_key) == lab["category"]
            r["got"] = {"amount_low": lo, "amount_high": hi, "price_type": g(it, "price_type"), "category": g(it, cat_key)}
        rows.append(r)
    return rows
