"""Live, hand-labelled SIE pipeline vs general chat LLM benchmark.

Run: .venv/bin/python -m bench.run
Both paths see the exact same source-verified excerpt per case. The comparison
model is Qwen3.8 27B via SIE Serverless, a general chat LLM, not a second SIE
extract/classify recipe. The app never reads benchmark labels or outputs.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from agent import read_document
from pipeline.classify import CRITERIA, QUESTION, classify
from pipeline.extract import SIE_LABELS, extract_quote
from pipeline.sie_client import _get_client

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
MODEL = "Qwen/Qwen3.8-27B-FP8"
FIELDS = ("price_type", "amount_low", "amount_high")
# USD per 1M tokens, from https://superlinked.com/models (list prices, Nov 2026).
USD_PER_M_EXTRACT = 0.186
USD_PER_M_CLASSIFY = 0.28
USD_PER_M_LLM_IN = 0.25
USD_PER_M_LLM_OUT = 2.75


def _plain_item(item: dict | None) -> dict:
    return {k: item.get(k) if item else None for k in ("category", *FIELDS)}


def _sie(case: dict) -> dict:
    start = time.perf_counter()
    items, traces = extract_quote(case["text"], case["source"], f"BENCH-{case['id']}-v1")
    items, ctraces = classify(items)
    elapsed = round((time.perf_counter() - start) * 1000)
    # Approximate token count from characters, including prompts/labels. This
    # is an estimate, not the server's billed amount.
    extract_chars = sum(t["input_chars"] for t in traces) + len(str(SIE_LABELS))
    classify_chars = sum(t["input_chars"] for t in ctraces) + len(QUESTION) + len(str(CRITERIA))
    usd = (extract_chars / 4 * USD_PER_M_EXTRACT + classify_chars / 4 * USD_PER_M_CLASSIFY) / 1_000_000
    return {"prediction": _plain_item(items[0] if items else None), "latency_ms": elapsed,
            "estimated_usd": usd, "item_count": len(items)}


def _llm(case: dict) -> dict:
    prompt = (
        "Read this single funeral quote line. Return ONLY one JSON object with keys "
        "category, price_type, amount_low, amount_high. Categories: basic_fee, optional, "
        "cash_advance, package, stated_requirement. Price types: fixed, estimated, "
        "starting_at, unknown. Use null for an unknown price or an open upper bound; "
        "a price explicitly stated as no additional charge may be zero. "
        "Do not infer a price from other lines.\n\nLINE: " + case["text"]
    )
    start = time.perf_counter()
    response = _get_client().chat_completions(
        MODEL, [{"role": "user", "content": prompt}], max_completion_tokens=180,
        extra_body={"temperature": 0, "top_p": 1},
    )
    elapsed = round((time.perf_counter() - start) * 1000)
    content = response["choices"][0]["message"]["content"] or ""
    try:
        obj = json.loads(content[content.index("{"):content.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        obj = {}
    usage = response.get("usage") or {}
    usd = (usage.get("prompt_tokens", 0) * USD_PER_M_LLM_IN
           + usage.get("completion_tokens", 0) * USD_PER_M_LLM_OUT) / 1_000_000
    return {"prediction": _plain_item(obj), "latency_ms": elapsed,
            "estimated_usd": usd, "raw": content, "usage": usage}


def _equal(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.01
    return a == b


def _score(rows: list[dict], system: str) -> dict:
    n = len(rows)
    correct_fields = sum(_equal(row[system]["prediction"].get(k), row["gold"][k])
                         for row in rows for k in FIELDS)
    correct_labels = sum(row[system]["prediction"].get("category") == row["gold"]["category"]
                         for row in rows)
    return {"fields": f"{correct_fields}/{n * len(FIELDS)}",
            "labels": f"{correct_labels}/{n}",
            "latency_ms": sum(row[system]["latency_ms"] for row in rows),
            "estimated_usd": sum(row[system]["estimated_usd"] for row in rows)}


def _brief(p: dict) -> str:
    return f"{p['category']}; {p['price_type']}; {p['amount_low']}–{p['amount_high']}"


def _markdown(rows: list[dict]) -> str:
    ss, ll = _score(rows, "sie"), _score(rows, "llm")
    out = ["# SIE vs general LLM on 13 hand-labelled quote lines", "",
           "Method: Each system saw the identical, source-verified line independently. SIE used the app's extract + classify pipeline (including code price parsing and explicit optional-service normalization); the general comparator was Qwen3.8 27B chat via the same hosted SIE account. No gold labels were in either prompt. All 13 cases, including errors, are below.", "",
           "| System | Price field accuracy (type, low, high) | Category accuracy | Total wall time | Estimated API cost |",
           "|---|---:|---:|---:|---:|",
           f"| SIE pipeline | {ss['fields']} | {ss['labels']} | {ss['latency_ms']} ms | ${ss['estimated_usd']:.6f} |",
           f"| Qwen chat | {ll['fields']} | {ll['labels']} | {ll['latency_ms']} ms | ${ll['estimated_usd']:.6f} |", "",
           "Cost method: approximate SIE tokens as input characters / 4 including label/question text, then apply [Superlinked's November 2026 list prices](https://superlinked.com/models) for GLiNER2 large ($0.186/M) and Decide ($0.28/M). Chat cost uses the API's prompt/completion token counts and the listed Qwen3.8 27B rates ($0.25/M input, $2.75/M output). These are estimates, not billed USD; SIE's per-call schema overhead and tokenizer may differ. Wall time includes network and any model startup.", "",
           "| Case (source) | Gold: category; type; low–high | SIE | Qwen chat | SIE ms | Chat ms |",
           "|---|---|---|---|---:|---:|"]
    for row in rows:
        out.append(f"| {row['id']} ({Path(row['source']).name}) | {_brief(row['gold'])} | "
                   f"{_brief(row['sie']['prediction'])} | {_brief(row['llm']['prediction'])} | "
                   f"{row['sie']['latency_ms']} | {row['llm']['latency_ms']} |")
    out += ["", "Raw predictions, timing, and usage metadata are in `results.json`. "
            "The public GPL lines are extraction tests only and never affect the fictional family plan.", ""]
    return "\n".join(out)


def main() -> None:
    cases = json.loads((HERE / "cases.json").read_text())
    rows = []
    for case in cases:
        source_text = read_document(ROOT / case["source"])
        if case["text"] not in source_text:
            raise ValueError(f"Hand-labelled line is absent from {case['source']}: {case['id']}")
        row = {"id": case["id"], "source": case["source"], "text": case["text"],
               "gold": _plain_item(case)}
        for system, run in (("sie", _sie), ("llm", _llm)):
            try:
                row[system] = run(case)
            except Exception as exc:
                row[system] = {"prediction": _plain_item(None), "latency_ms": 0,
                               "estimated_usd": 0.0, "error": f"{type(exc).__name__}: {exc}"}
        rows.append(row)
        print(case["id"], "SIE", row["sie"]["prediction"], "LLM", row["llm"]["prediction"], flush=True)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    (HERE / "results.md").write_text(_markdown(rows))
    print("Wrote bench/results.md and bench/results.json")


if __name__ == "__main__":
    main()
