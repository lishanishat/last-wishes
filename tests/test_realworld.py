"""Offline well-formedness checks for bench/realworld (no network, no pipeline calls)."""
import json
import re
from pathlib import Path

RW = Path(__file__).resolve().parent.parent / "bench" / "realworld"
CATS = {"basic_fee", "optional", "cash_advance", "package", "stated_requirement"}
PTS = {"fixed", "estimated", "starting_at", "unknown"}


def _labels():
    return json.loads((RW / "labels.json").read_text())


def _text(src):
    return (RW / f"{src}.txt").read_text()


def test_docs_have_provenance_headers():
    docs = sorted(RW.glob("gpl_*.txt"))
    assert len(docs) >= 8
    sources_md = (RW / "SOURCES.md").read_text()
    for p in docs:
        head = p.read_text().splitlines()[:2]
        assert head[0].startswith("# SOURCE_URL: http"), p.name
        assert head[1] == "# CAPTURED: 2026-11-20", p.name
        assert head[0].split(": ", 1)[1] in sources_md, p.name
        assert len(p.read_text()) > 2000


def test_labels_well_formed():
    labels = _labels()
    assert len(labels) >= 40
    ids = [l["id"] for l in labels]
    assert len(ids) == len(set(ids))
    for l in labels:
        assert (RW / f"{l['source']}.txt").exists(), l["id"]
        assert l["category"] in CATS and l["price_type"] in PTS, l["id"]
        re.compile(l["match"])
        lo, hi = l["amount_low"], l["amount_high"]
        if l["price_type"] == "unknown":
            assert lo is None and hi is None, l["id"]
        else:
            assert lo is not None and lo >= 0, l["id"]
            assert hi is None or hi >= lo, l["id"]
        if l["price_type"] == "estimated":
            assert hi is not None and hi > lo, l["id"]
        assert isinstance(l["alt_amounts"], list)
        assert l["evidence"].strip(), l["id"]


def test_label_amounts_appear_in_source_text():
    """A labeled amount must literally occur in the GPL text (guards against typos in hand labels)."""
    for l in _labels():
        t = re.sub(r"[,\s]", "", _text(l["source"]))
        for v in (l["amount_low"], l["amount_high"]):
            if v is None or v == 0:
                continue
            forms = {f"{v:.2f}", f"{v:g}", f"{int(v)}" if float(v).is_integer() else f"{v:.2f}"}
            assert any(f in t for f in forms), f"{l['id']}: {v} not found in {l['source']}.txt"
