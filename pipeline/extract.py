"""Quote / reply extraction -> list[LineItem] (LAST_WISHES.md §8 step 2, §9).

How it works (no provider-specific code):
  1. Code splits the document into candidate segments with exact character offsets:
     table rows, bullet lines, single short lines, and sentences of prose paragraphs.
     Each segment's raw substring is the item's ``excerpt``, so it is verbatim by construction
     (and re-validated against the source text before an item is emitted).
  2. SIE extract (GLiNER2, ``pipeline.sie_client.extract``) runs on every segment with labels
     for services / merchandise / fees / prices / requirements. Its spans name prose items and
     give the item's confidence. A span whose text is not in the segment is ignored.
  3. Money and price type are parsed in CODE from the excerpt (``parse_price``), never taken
     from a model: ``$1,195`` / ``1195.00`` / ``1,195 USD`` / ranges ``$24–$48`` /
     ``starting at $X`` / ``est. $96`` / ``TBC``. Missing price -> ``unknown`` with
     ``amount_low = amount_high = None`` (never 0).
  4. Totals ("Quoted total", "come to", ...) are skipped; statements with requirement wording
     ("... is required ...") are kept as price-less items so SIE classify can label them
     ``stated_requirement``.

``category`` is a placeholder ("basic_fee") until ``pipeline.classify.classify`` runs.

Script mode:  .venv/bin/python -m pipeline.extract data/quote_B.txt B-v1
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from contracts import LineItem, SIETrace

# ----------------------------------------------------------------------------- money parsing

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
# A money token: $X | X USD | X dollars | bare X.XX (two decimals).
_MONEY_RE = re.compile(
    rf"(?:US)?\$\s?(?P<a>{_NUM})"
    rf"|(?P<b>{_NUM})\s?(?:USD|usd|dollars?\b)"
    r"|(?<![\d,.$])(?P<c>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})(?![\d%])"
)
# Between two money tokens to make a range ("$24–$48", "$24 - 48", "$24 to $48").
_RANGE_SEP_RE = re.compile(r"^\s*(?:[-–—]|to|and)\s*$", re.I)
_RANGE_SECOND_RE = re.compile(rf"\s*(?:[-–—]|to|and)\s*(?:US)?\$?\s?(?P<n>{_NUM})(?:\s?(?:USD|dollars?))?")

_STARTING_RE = re.compile(
    r"(starting\s+(?:at|from)|starts?\s+at|from|as\s+low\s+as|beginning\s+at|minimum(?:\s+of)?|at\s+least)\s*$",
    re.I,
)
_ESTIMATE_RE = re.compile(
    r"(est\.?|estimated(?:\s+at)?|estimate(?:\s+of)?|approx\.?|approximately|about|around|roughly|~|up\s+to|plan\s+on(?:\s+an?)?(?:\s+estimated)?)\s*$",
    re.I,
)
_ESTIMATE_ANYWHERE_RE = re.compile(r"\b(est\.|estimated|estimate|approx|approximately)\b", re.I)
# Amounts that describe an old/superseded value ("was listed at $150", "previously $150").
_OLD_RE = re.compile(
    r"(previously(?:\s+(?:stated|listed|quoted))?(?:\s+(?:as|at))?|formerly|originally|was\s+(?:listed|quoted|stated)\s+(?:at|as)"
    r"|was|instead\s+of|old\s+price(?:\s+of)?|down\s+from|up\s+from)\s*$",
    re.I,
)
_PER_UNIT_RE = re.compile(r"^\s*(each|per\s+\w+|/\s*\w+|a\s+copy|apiece)\b", re.I)
_NO_CHARGE_RE = re.compile(
    r"\b(no\s+(?:additional\s+|extra\s+)?charge|free\s+of\s+charge|at\s+no\s+(?:additional\s+|extra\s+)?cost|no\s+cost)\b",
    re.I,
)
UNKNOWN_RE = re.compile(
    r"\b(TBC|TBD|TBA|to\s+be\s+(?:confirmed|determined|advised|announced)|not\s+(?:yet\s+)?(?:included|listed|priced|quoted)"
    r"|price\s+on\s+request|upon\s+request|on\s+request|call\s+for\s+(?:price|pricing)|pending)\b",
    re.I,
)


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


@dataclass
class Money:
    value: float
    start: int
    end: int


def find_money(text: str) -> list[Money]:
    """All money tokens in ``text`` with offsets."""
    out = []
    for m in _MONEY_RE.finditer(text):
        raw = m.group("a") or m.group("b") or m.group("c")
        out.append(Money(_to_float(raw), m.start(), m.end()))
    return out


def current_amounts(excerpt: str, monies: Optional[list[Money]] = None) -> list[Money]:
    """Money tokens minus superseded ones ("was listed at $150, but ... it is $195")."""
    monies = find_money(excerpt) if monies is None else monies
    current = [m for m in monies if not _OLD_RE.search(excerpt[max(0, m.start - 30) : m.start])]
    return current or monies[-1:]


def parse_price(excerpt: str) -> tuple[str, Optional[float], Optional[float]]:
    """(price_type, amount_low, amount_high) parsed from a verbatim excerpt.

    price_type in fixed|estimated|starting_at|unknown. Unknown -> (unknown, None, None).
    Never returns 0 for a missing price; 0.0 only for explicit "no charge" wording.
    """
    monies = find_money(excerpt)
    if not monies:
        if _NO_CHARGE_RE.search(excerpt):
            return "fixed", 0.0, 0.0
        return "unknown", None, None

    current = current_amounts(excerpt, monies)

    # Ranges: money, separator, number.
    for m in current:
        r = _RANGE_SECOND_RE.match(excerpt, m.end)
        if r:
            lo, hi = m.value, _to_float(r.group("n"))
            if hi >= lo:
                before = excerpt[max(0, m.start - 30) : m.start]
                if _STARTING_RE.search(before) and not re.search(r"\bfrom\s*$", before, re.I):
                    return "starting_at", lo, None
                return "estimated", lo, hi

    # Prefer amounts that are not per-unit ("$24 each") when there are others.
    whole = [m for m in current if not _PER_UNIT_RE.match(excerpt[m.end : m.end + 12])]
    pick = (whole or current)[0]
    before = excerpt[max(0, pick.start - 30) : pick.start]
    if _STARTING_RE.search(before):
        return "starting_at", pick.value, None
    if _ESTIMATE_RE.search(before):
        return "estimated", pick.value, pick.value
    return "fixed", pick.value, pick.value


# ----------------------------------------------------------------------------- segmentation

_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
_BULLET_BODY = r"\s*(?:[•\*·▪◦‣]|[-–—](?=\s)|\d{1,2}[.)](?=\s))\s*"
_BULLET_RE = re.compile("^" + _BULLET_BODY)
_BULLET_AT_RE = re.compile(_BULLET_BODY)  # for .match(source, pos, endpos)
_SENT_END_RE = re.compile(r"(?<=[.!?])[\")\]]?\s+(?=[\"(\[]?[A-Z$])")
# A line break after a figure / closing paren, followed by a capitalised line, also ends a
# sentence ("Quoted total: $895.00\nA casket purchase is required ...").
_LINE_END_RE = re.compile(r"(?<=[\d)])[ \t]*\n(?=[ \t]*[\"(]?[A-Z])")
_TOTAL_RE = re.compile(
    r"\b(sub-?total|total|totals|altogether|come\s+to|comes\s+to|itemi[sz]ed\s+value|grand\s+total|balance\s+due|amount\s+due)\b",
    re.I,
)
REQUIREMENT_RE = re.compile(
    r"\b(required|requires|require|requirement|must|mandatory|obligatory|compulsory|necessary|need\s+to\s+(?:buy|purchase))\b",
    re.I,
)


@dataclass
class Segment:
    start: int
    end: int
    text: str          # == source[start:end]
    kind: str          # table | bullet | line | prose
    cells: list[str]   # table cells (table rows only)


def _trim(source: str, start: int, end: int) -> tuple[int, int]:
    """Trim whitespace, bullet markers and an unbalanced wrapping paren; offsets stay exact."""
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    m = _BULLET_AT_RE.match(source, start, end)
    if m and m.end() > start:
        start = m.end()
    seg = source[start:end]
    if seg.startswith("(") and seg.count("(") > seg.count(")"):
        start += 1
    seg = source[start:end]
    if seg.endswith(")") and seg.count(")") > seg.count("("):
        end -= 1
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    return start, end


def segment(source: str) -> list[Segment]:
    """Split a document into candidate segments with exact offsets into ``source``."""
    lines: list[tuple[int, int]] = []
    pos = 0
    for raw in source.splitlines(keepends=True):
        lines.append((pos, pos + len(raw.rstrip("\r\n"))))
        pos += len(raw)

    segs: list[Segment] = []
    para: list[tuple[int, int]] = []

    def flush_para() -> None:
        if not para:
            return
        p_start, p_end = para[0][0], para[-1][1]
        kind = "line" if len(para) == 1 else "prose"
        cut = p_start
        bounds = sorted(
            {m.end() for m in _SENT_END_RE.finditer(source, p_start, p_end)}
            | {m.end() for m in _LINE_END_RE.finditer(source, p_start, p_end)}
        )
        for b in bounds + [p_end]:
            s, e = _trim(source, cut, b)
            if e > s:
                segs.append(Segment(s, e, source[s:e], kind, []))
            cut = b
        para.clear()

    for i, (ls, le) in enumerate(lines):
        line = source[ls:le]
        if not line.strip():
            flush_para()
            continue
        if line.lstrip().startswith("|") or line.count("|") >= 2:
            flush_para()
            if _TABLE_SEP_RE.match(line):
                continue
            nxt = source[lines[i + 1][0] : lines[i + 1][1]] if i + 1 < len(lines) else ""
            if _TABLE_SEP_RE.match(nxt):
                continue  # header row
            s, e = _trim(source, ls, le)
            cells = [c.strip() for c in source[s:e].strip("|").split("|")]
            segs.append(Segment(s, e, source[s:e], "table", cells))
            continue
        if _BULLET_RE.match(line) and not re.match(r"^\s*\$", line):
            flush_para()
            s, e = _trim(source, ls, le)
            if e > s:
                segs.append(Segment(s, e, source[s:e], "bullet", []))
            continue
        para.append((ls, le))
    flush_para()
    return segs


# ----------------------------------------------------------------------------- naming

_LABEL_SPLIT_RE = re.compile(r"\s+[—–]\s+|\s+-\s+|:\s+")


def structured_name(seg: Segment) -> Optional[str]:
    """Item name from structure: first table cell, or the label left of ' — ' / ':'."""
    if seg.kind == "table":
        for c in seg.cells:
            if c:
                return c
        return None
    if seg.kind in ("bullet", "line") or ("\n" not in seg.text and len(seg.text) < 120):
        parts = _LABEL_SPLIT_RE.split(seg.text, maxsplit=1)
        if len(parts) == 2:
            right = parts[1]
            if find_money(right) or UNKNOWN_RE.search(right) or _NO_CHARGE_RE.search(right):
                return parts[0].strip()
    return None


def fallback_name(text: str) -> str:
    """Name for a prose segment with no SIE span: text before the first price, tidied."""
    monies = find_money(text)
    head = text[: monies[0].start] if monies else text
    head = re.sub(r"\b(is|are|costs?|will\s+be|of|at|for|was|be|totals?)\s*$", "", head.strip(), flags=re.I)
    head = head.strip(" ,;:—–-")
    return (head[:80].rstrip() or text[:80]).strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def excerpt_in_text(excerpt: str, text: str) -> bool:
    """Verbatim check (whitespace-insensitive, so a sentence wrapped over lines still counts)."""
    if not excerpt:
        return False
    if excerpt in text:
        return True
    squash = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    return squash(excerpt) in squash(text)


# ----------------------------------------------------------------------------- extraction

SIE_LABELS = [
    "funeral service",
    "funeral merchandise",
    "fee or charge",
    "price",
    "purchase requirement",
]
_NAME_LABELS = {"funeral service", "funeral merchandise", "fee or charge"}
_FALLBACK_CONFIDENCE = 0.5


def provider_of(quote_id: str) -> str:
    return quote_id.split("-", 1)[0]


def build_items(
    text: str,
    source_doc: str,
    quote_id: str,
    entities_per_segment: Optional[list[list[dict]]] = None,
    segments: Optional[list[Segment]] = None,
) -> list[LineItem]:
    """Turn segments (+ SIE entities per segment, if any) into validated LineItems.

    Pure code, no network: exposed so tests and the benchmark can run it offline.
    """
    segs = segments if segments is not None else segment(text)
    ents = entities_per_segment if entities_per_segment is not None else [[] for _ in segs]
    provider = provider_of(quote_id)
    items: list[LineItem] = []
    seen: dict[str, int] = {}

    for seg, seg_ents in zip(segs, ents):
        t = seg.text
        has_money = bool(find_money(t)) or bool(_NO_CHARGE_RE.search(t))
        has_unknown = bool(UNKNOWN_RE.search(t))
        is_requirement = bool(REQUIREMENT_RE.search(t))
        if not (has_money or has_unknown or is_requirement):
            continue
        # Totals are summaries, not items.
        label_part = structured_name(seg) or t
        if _TOTAL_RE.search(label_part) or (seg.kind == "prose" and _TOTAL_RE.search(t)):
            continue

        # Valid SIE spans: text really in the segment.
        spans = [
            e for e in seg_ents
            if isinstance(e.get("text"), str) and e["text"].strip() and e["text"] in t
        ]
        name_spans = sorted(
            (e for e in spans if e.get("label") in _NAME_LABELS),
            key=lambda e: float(e.get("score") or 0),
            reverse=True,
        )
        req_spans = [e for e in spans if e.get("label") == "purchase requirement"]

        if is_requirement and not has_money:
            name = t.strip()
            conf = max([float(e.get("score") or 0) for e in req_spans + name_spans] or [_FALLBACK_CONFIDENCE])
        else:
            name = structured_name(seg) or (name_spans[0]["text"].strip() if name_spans else fallback_name(t))
            conf = float(name_spans[0].get("score") or 0) if name_spans else _FALLBACK_CONFIDENCE

        price_type, low, high = parse_price(t)
        if has_unknown and not find_money(t):
            price_type, low, high = "unknown", None, None
        # Several distinct amounts in one segment: the pick may be wrong -> lower confidence.
        distinct = {m.value for m in current_amounts(t)}
        if len(distinct) > 1 and price_type == "fixed":
            conf *= 0.8

        name = re.sub(r"\s+", " ", name).strip()
        # Excerpt validation: must appear in the source.
        if not excerpt_in_text(t, text):
            continue
        conf = round(max(0.0, min(1.0, conf)), 3)

        key = _norm(name)
        if key in seen:
            prev = items[seen[key]]
            if prev["price_type"] == "unknown" and price_type != "unknown":
                prev.update(price_type=price_type, amount_low=low, amount_high=high, excerpt=t, confidence=conf)
                continue
            if prev["excerpt"] == t or (prev["amount_low"], prev["amount_high"]) == (low, high):
                continue  # the same item mentioned again
            # Same short SIE name on a different service with a different price (e.g. "cremation"
            # for both the container and the medical examiner authorization): keep both.
            alt = re.sub(r"\s+", " ", fallback_name(t)).strip()
            name = alt if _norm(alt) not in seen else f"{name} ({len(items) + 1})"
            key = _norm(name)
        seen[key] = len(items)
        items.append(
            LineItem(
                item_id="",
                quote_id=quote_id,
                provider=provider,
                name=name,
                category="basic_fee",  # placeholder until pipeline.classify runs
                price_type=price_type,  # type: ignore[typeddict-item]
                amount_low=low,
                amount_high=high,
                excerpt=t,
                source_doc=source_doc,
                confidence=conf,
            )
        )
    for n, item in enumerate(items, start=1):
        item["item_id"] = f"{provider}-{n:02d}"
    return items


def extract_quote(text: str, source_doc: str, quote_id: str) -> tuple[list[LineItem], list[SIETrace]]:
    """Extract LineItems from any quote / price list / provider reply text using SIE extract."""
    from pipeline import sie_client

    segs = segment(text)
    if not segs:
        return [], []
    ents, traces = sie_client.extract([s.text for s in segs], SIE_LABELS)
    return build_items(text, source_doc, quote_id, ents, segs), traces


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m pipeline.extract <file> <quote_id>", file=sys.stderr)
        return 2
    from pipeline import sie_client
    from pipeline.classify import classify

    if not sie_client.has_key():
        print("SIE_API_KEY not set (.env) - skipping live run.", file=sys.stderr)
        return 1
    path = Path(argv[0])
    items, traces = extract_quote(path.read_text(encoding="utf-8"), path.name, argv[1])
    items, ctraces = classify(items)
    for it in items:
        amt = (
            "unknown" if it["amount_low"] is None
            else f"{it['amount_low']:,.2f}" + ("" if it["amount_high"] == it["amount_low"]
                                               else f"-{it['amount_high']:,.2f}" if it["amount_high"] is not None else "+")
        )
        print(f"{it['item_id']:6} {it['category']:18} {it['price_type']:11} {amt:>18}  "
              f"conf={it['confidence']:.2f}  {it['name']}")
        print(f"       excerpt: {it['excerpt']!r}")
    for tr in traces + ctraces:
        print(f"trace: {tr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
