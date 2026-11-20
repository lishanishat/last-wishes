"""Drafting and explanations (LAST_WISHES.md §3: the LLM only explains and drafts).

The LLM never decides compliance, computes numbers, or approves anything.
Every number placed in a prompt is pre-formatted here from validated data
(extracted items, optimizer output, the code-built diff). Output is checked:
if it introduces a dollar figure that was not in the facts, or uses banned
wording, the deterministic template is used instead.

If ANTHROPIC_API_KEY is missing (or the call fails), a template is returned,
clearly labeled "(template draft — LLM unavailable)".
"""
from __future__ import annotations

import os
import re
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

MODEL = "claude-sonnet-5-5"
TEMPLATE_LABEL = "(template draft — LLM unavailable)"
BANNED = re.compile(r"\b(illegal|unlawful|violat\w*|purchased|booked)\b", re.I)
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")

SYSTEM = (
    "You write short, calm, plain messages for a family arranging a funeral. "
    "Use ONLY the facts given. Never add, change, or compute any number or dollar amount; "
    "copy amounts exactly as given. Never make legal judgments: do not say anything is "
    "illegal, unlawful, or a violation. Never say anything was purchased or booked. "
    "No greetings beyond one line, no sign-off name placeholders like [Name]. "
    "Return only the message text."
)


def money(low: Optional[float], high: Optional[float] = None, price_type: Optional[str] = None) -> str:
    if price_type == "unknown" or (low is None and high is None):
        return "unresolved"
    if high is None and price_type == "starting_at":
        return f"from ${low:,.0f}"
    if low is None:
        return f"up to ${high:,.0f}"
    if high is None or abs(high - low) < 0.005:
        return f"${low:,.2f}".replace(".00", "")
    return f"${low:,.0f}–${high:,.0f}"


def _llm(prompt: str, max_tokens: int = 400) -> Optional[str]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content).strip()
        return text or None
    except Exception:
        return None


def _safe(llm_text: Optional[str], facts_text: str) -> bool:
    """LLM output may only repeat dollar figures present in the facts, and no banned words."""
    if not llm_text or BANNED.search(llm_text):
        return False
    allowed = {re.sub(r"[\s,]", "", m) for m in _MONEY.findall(facts_text)}
    allowed |= {a.replace(".00", "") for a in allowed}
    for m in _MONEY.findall(llm_text):
        norm = re.sub(r"[\s,]", "", m)
        if norm not in allowed and norm.replace(".00", "") not in allowed:
            return False
    return True


def _template(text: str) -> str:
    return f"{TEMPLATE_LABEL}\n\n{text}"


# ---------------------------------------------------------------------------
# Clarification (pipeline step 9)
# ---------------------------------------------------------------------------


def flag_subject(flag: dict) -> str:
    """What a flag is about, from its own message (e.g. 'crematory fee'), for items not on the quote."""
    m = re.search(r"clarification:\s*(.+?)\s+has no stated price", flag.get("message") or "", re.I)
    return m.group(1) if m else "a charge"


def _flag_facts(flags: list[dict], items: dict | None) -> tuple[list[str], list[str]]:
    unresolved, statements = [], []
    for f in flags:
        it = (items or {}).get(f.get("item_id")) or {}
        if f.get("kind") == "unresolved_charge":
            name = it.get("name") or flag_subject(f)
            unresolved.append(f"{name} (your statement: \"{(f.get('excerpt') or '').strip()}\")")
        elif f.get("kind") == "stated_requirement":
            statements.append((f.get("excerpt") or "").strip())
    return unresolved, statements


def template_clarification(flags: list[dict], plan: Optional[dict], provider: str,
                           items: dict | None = None) -> str:
    unresolved, statements = _flag_facts(flags, items)
    lines = [f"Hello Provider {provider} team,", "",
             "Thank you for the quote. Before our family decides, could you help with the following?", ""]
    n = 1
    for u in unresolved:
        lines.append(f"{n}. The quote does not list a price for: {u}. Could you tell us this charge, "
                     "and whether it is fixed or an estimate?")
        n += 1
    for s in statements:
        lines.append(f"{n}. Your quote says: \"{s}\" Could you clarify this requirement, and quote the "
                     "alternative-container option for direct cremation?")
        n += 1
    lines += ["", "Thank you for your help.", "On behalf of the family"]
    return "\n".join(lines)


def draft_clarification(flags: list[dict], plan: Optional[dict], provider: str,
                        items: dict | None = None) -> str:
    """Narrow question: ask only for the unresolved fee(s) and/or the casket-statement clarification."""
    template = template_clarification(flags, plan, provider, items)
    unresolved, statements = _flag_facts(flags, items)
    facts = []
    if unresolved:
        facts.append("Charges with no price on the quote (ask for the price and whether it is fixed or estimated): "
                     + "; ".join(unresolved))
    if statements:
        facts.append("Provider statements to ask them to clarify (also ask them to quote the "
                     "alternative-container option for direct cremation): "
                     + "; ".join(f'"{s}"' for s in statements))
    facts_text = "\n".join(facts)
    prompt = (
        f"Write a short clarification email to funeral provider {provider} on behalf of the family. "
        "Ask only these narrow questions, numbered, quoting the provider's own words where given. "
        "Do not mention any total or any other price. Do not mention laws or regulators.\n\n"
        f"FACTS:\n{facts_text}"
    )
    out = _llm(prompt)
    return out if _safe(out, facts_text) else _template(template)


# ---------------------------------------------------------------------------
# What changed and why (pipeline step 14)
# ---------------------------------------------------------------------------


def _change_sentences(diff: dict) -> list[str]:
    out = []
    order = {"resolved": 0, "changed": 1, "added": 2, "removed": 3}
    lines = sorted(diff.get("lines") or [], key=lambda r: order.get(r.get("status"), 9))
    for r in lines:
        name = (r.get("name") or "charge").strip()
        low = name[0].lower() + name[1:] if name else name
        if r.get("status") == "resolved":
            out.append(f"You reviewed this while the price for {low} was unresolved. The reply sets it at {r.get('v2')}.")
        elif r.get("status") == "changed":
            out.append(f"The reply changes the {low} from {r.get('v1')} to {r.get('v2')}.")
        elif r.get("status") == "added":
            out.append(f"The reply adds {low} at {r.get('v2')}.")
        elif r.get("status") == "removed":
            out.append(f"The reply no longer lists {low} (was {r.get('v1')}).")
    op, np_ = diff.get("old_plan"), diff.get("new_plan")
    if op and np_ and op.get("known_total") is not None and np_.get("known_total") is not None:
        out.append(f"The plan's known total moves from {money(op['known_total'])} to {money(np_['known_total'])}.")
        if op.get("unresolved") and not np_.get("unresolved"):
            out.append("No charges in this plan are unresolved now.")
        elif np_.get("unresolved"):
            out.append("Still unresolved: " + ", ".join(np_["unresolved"]) + ".")
    return out


def explain_change(diff: dict, recall: Optional[dict] = None) -> str:
    sentences = _change_sentences(diff)
    if not sentences:
        return _template("The reply did not change any priced line.")
    template = " ".join(sentences)
    memory = (recall or {}).get("answer") or ""
    facts_text = "\n".join(f"- {s}" for s in sentences)
    prompt = (
        "Rewrite these facts as two to four calm, plain sentences for the family. The first sentence must be "
        "in the form: 'You reviewed this while the price for <charge> was unresolved. The reply sets it at <amount>.' "
        "when such a fact is present. Keep every amount exactly as written.\n\n"
        f"FACTS:\n{facts_text}\n\nMEMORY CONTEXT (do not take numbers from here):\n{memory[:800]}"
    )
    out = _llm(prompt, max_tokens=300)
    return out if _safe(out, facts_text) else _template(template)


# ---------------------------------------------------------------------------
# Arrangement request (pipeline step 17) — deterministic; no LLM needed
# ---------------------------------------------------------------------------


def draft_arrangement(plan: dict, services: list[dict], provider: str, quote_id: str) -> str:
    lines = [f"Hello Provider {provider} team,", "",
             f"Our family would like to request the following arrangement, based on your quote {quote_id}:", ""]
    for s in services:
        lines.append(f"- {s.get('name')}: {money(s.get('amount_low'), s.get('amount_high'), s.get('price_type'))}")
    est_hi = plan.get("estimated_high")
    est = money(plan.get("estimated_low") or 0, est_hi, None if est_hi is not None else "starting_at")
    lines += ["", f"Known charges: {money(plan.get('known_total'))}",
              f"Estimated charges: {est}"]
    if plan.get("unresolved"):
        lines.append("Unresolved: " + ", ".join(plan["unresolved"]))
    lines += ["", "This is a request, not a payment. Please confirm availability and next steps in writing, "
              "with an itemized statement.", "", "Thank you,", "On behalf of the family"]
    return "\n".join(lines)
