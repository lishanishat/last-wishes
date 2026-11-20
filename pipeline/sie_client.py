"""Thin wrapper around Superlinked SIE (Serverless) for the three recipes we use.

Every public call returns ``(result, trace)`` where ``trace`` is a ``contracts.SIETrace``
(recipe, model, latency_ms, input_chars), so the orchestrator can log it to ``sie_calls``.

API source (read before writing this file, not guessed):
  * https://superlinked.com/serverless   - endpoints, Bearer auth, base URL https://api.superlinked.com
  * https://superlinked.com/classify     - zero-shot classification via /v1/extract + fastino/GLiNER2.5-Decide
  * https://superlinked.com/named-entities - span extraction via /v1/extract with params.labels
  * https://github.com/superlinked/cookbook (insurance/check_invoice_against_claim,
    retail/route_customer_emails, legal/check_contracts_for_required_clauses) - SDK usage,
    Decide ``output_schema`` "choice" questions, ``client.score`` for reranking.

Transport: the official Python SDK ``sie-sdk`` (``from sie_sdk import SIEClient``), which posts
to ``POST /v1/extract/{model}`` and ``POST /v1/score/{model}`` with ``Authorization: Bearer``
and retries cold-start 503s (PROVISIONING / MODEL_LOADING) for us.

Config: SIE_API_KEY (required) and SIE_BASE_URL (optional, default https://api.superlinked.com)
are read from the environment / ``.env``. Never hard-code keys.
"""
from __future__ import annotations

import os
import time
from typing import Any, Iterable

from dotenv import load_dotenv

from contracts import SIETrace

DEFAULT_BASE_URL = "https://api.superlinked.com"

# Models (names from superlinked.com/serverless and the cookbook rules.yaml files).
EXTRACT_MODEL = "fastino/gliner2-large-v1"       # span extraction (GLiNER2)
CLASSIFY_MODEL = "fastino/GLiNER2.5-Decide"      # zero-shot choice / classification
RERANK_MODEL = "Qwen/Qwen3-Reranker-4B"          # cross-encoder reranker via /v1/score

# Cold models can take minutes to start; the SDK waits up to this long for capacity.
WAIT_S = float(os.environ.get("SIE_WAIT_S", "600"))
# Items per /v1/extract request (one trace per request).
BATCH_SIZE = 16

_client: Any = None


def _get_client() -> Any:
    """Lazily build one SIEClient. Raises RuntimeError if the key is missing."""
    global _client
    if _client is not None:
        return _client
    load_dotenv()
    api_key = os.environ.get("SIE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SIE_API_KEY not set")
    base_url = os.environ.get("SIE_BASE_URL", "").strip() or DEFAULT_BASE_URL
    try:
        from sie_sdk import SIEClient  # imported lazily so offline tests don't need it
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("sie-sdk not installed: pip install 'sie-sdk==0.11.1'") from e
    _client = SIEClient(base_url=base_url, api_key=api_key, timeout_s=WAIT_S)
    return _client


def has_key() -> bool:
    load_dotenv()
    return bool(os.environ.get("SIE_API_KEY", "").strip())


def _trace(recipe: str, model: str, t0: float, input_chars: int) -> SIETrace:
    return SIETrace(
        recipe=recipe,
        model=model,
        latency_ms=int(round((time.perf_counter() - t0) * 1000)),
        input_chars=int(input_chars),
    )


def _plain(value: Any) -> Any:
    """SDK results may hold numpy scalars/arrays; make them plain Python."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _batches(seq: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# --------------------------------------------------------------------------- extract


def extract(
    texts: list[str],
    labels: list[str],
    *,
    model: str = EXTRACT_MODEL,
    threshold: float | None = 0.3,
) -> tuple[list[list[dict]], list[SIETrace]]:
    """Entity-span extraction (``POST /v1/extract/{model}`` with ``params.labels``).

    Returns one list of entities per input text. Each entity is
    ``{"text", "label", "score", "start", "end"}`` with offsets into that input text.
    One trace per HTTP request (texts are batched ``BATCH_SIZE`` per request).
    """
    client = _get_client()
    out: list[list[dict]] = []
    traces: list[SIETrace] = []
    options = {"threshold": threshold} if threshold is not None else None
    for batch in _batches(list(texts), BATCH_SIZE):
        t0 = time.perf_counter()
        results = client.extract(
            model,
            [{"id": f"x{i}", "text": t} for i, t in enumerate(batch)],
            labels=labels,
            options=options,
            provision_timeout_s=WAIT_S,
        )
        traces.append(_trace("extract", model, t0, sum(len(t) for t in batch)))
        for res in results:
            res = _plain(res) or {}
            if res.get("error"):
                out.append([])
                continue
            out.append(list(res.get("entities") or []))
    return out, traces


# --------------------------------------------------------------------------- classify

_QUESTION_ID = "category"


def classify(
    texts: list[str],
    criteria: dict[str, str],
    *,
    question: str,
    model: str = CLASSIFY_MODEL,
) -> tuple[list[dict[str, float]], list[SIETrace]]:
    """Zero-shot single-choice classification with GLiNER2.5-Decide.

    Uses ``/v1/extract/{model}`` with an ``output_schema`` "choice" question (pattern from the
    cookbook's retail/route_customer_emails). ``criteria`` maps label -> short description.
    Returns one ``{label: probability}`` dict per text (empty dict if the item failed).
    If the reply has no ``data`` but has ``classifications`` (labels mode, per
    superlinked.com/classify), those scores are used instead.
    """
    client = _get_client()
    schema = {
        _QUESTION_ID: {"type": "choice", "instructions": question, "criteria": dict(criteria)}
    }
    out: list[dict[str, float]] = []
    traces: list[SIETrace] = []
    for batch in _batches(list(texts), BATCH_SIZE):
        t0 = time.perf_counter()
        results = client.extract(
            model,
            [{"id": f"c{i}", "text": t} for i, t in enumerate(batch)],
            output_schema=schema,
            provision_timeout_s=WAIT_S,
        )
        traces.append(_trace("classify", model, t0, sum(len(t) for t in batch)))
        for res in results:
            out.append(_probabilities(_plain(res) or {}, criteria))
    return out, traces


def _probabilities(res: dict, criteria: dict[str, str]) -> dict[str, float]:
    if res.get("error"):
        return {}
    answer = (res.get("data") or {}).get(_QUESTION_ID)
    if isinstance(answer, dict) and answer.get("probabilities"):
        return {
            str(k): float(v) for k, v in answer["probabilities"].items() if str(k) in criteria
        }
    if isinstance(answer, str) and answer in criteria:
        return {answer: 1.0}
    cls = res.get("classifications") or []
    return {str(c["label"]): float(c["score"]) for c in cls if str(c.get("label")) in criteria}


# --------------------------------------------------------------------------- rerank


def rerank(
    query: str, texts: list[str], *, model: str = RERANK_MODEL
) -> tuple[list[tuple[int, float]], SIETrace]:
    """Rerank ``texts`` against ``query`` (``POST /v1/score/{model}``).

    Returns ``[(index_into_texts, score), ...]`` sorted best first.
    """
    client = _get_client()
    t0 = time.perf_counter()
    res = client.score(
        model,
        {"text": query},
        [{"id": str(i), "text": t} for i, t in enumerate(texts)],
        provision_timeout_s=WAIT_S,
    )
    trace = _trace("rerank", model, t0, len(query) + sum(len(t) for t in texts))
    scores = _plain(res).get("scores") or []
    ranked = [(int(s["item_id"]), float(s["score"])) for s in scores]
    ranked.sort(key=lambda p: p[1], reverse=True)
    return ranked, trace
