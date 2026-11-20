"""Cognee memory for Last Wishes (LAST_WISHES.md §9 Memory API, §11 graph).

Two layers, both stored by Cognee under the project directory:

1. **Structured graph** (always on, no LLM needed): custom Cognee ``DataPoint`` models
   written with ``cognee.tasks.storage.add_data_points``. Edges are exact and named as in
   spec §11 (STATED, SOURCED_FROM, CONFIRMED, HAS_ROLE, OFFERS, CONTAINS, SUPERSEDES,
   ABOUT, ANSWERS, BASED_ON, HONORS, plus OMITS / REGARDING / ASKED_OF / PRODUCED /
   RESOLVES). Every node's ``text`` field is embedded (fastembed, local) so Cognee's
   own graph retrieval can find it.
2. **Semantic layer** (only when an LLM key is configured): the raw wish text goes
   through ``cognee.add`` + ``cognee.cognify`` so Cognee extracts its own entities.

``recall`` runs ``cognee.search(query_type=GRAPH_COMPLETION, only_context=True,
verbose=True)`` and returns the real edges Cognee retrieved (``objects_result``), with
node properties read back from Cognee's graph engine. It also attaches "standing
context" (Linda's wishes and open questions, read from the same graph), marked
``via="standing_context"`` so the UI can show which part came from search. The answer
is written by Cognee's configured LLM (``LLMGateway``) over exactly those nodes/edges,
or composed from the graph without an LLM when no key is set.

Every public function is synchronous (Streamlit-friendly). Calls run on one private
background event loop, so they are safe inside an already-running loop.

CLI:
    python -m memory.cognee_mem selftest
    python -m memory.cognee_mem recall "What was pending with Provider A?"
    python -m memory.cognee_mem counterfactual "Should we take Provider C's package?" W3
    python -m memory.cognee_mem snapshot
    python -m memory.cognee_mem reset
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import threading
import types
from pathlib import Path
from typing import Any, Coroutine, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET = "last_wishes"
DEFAULT_ANTHROPIC_MODEL = "anthropic/claude-opus-5-5"

log = logging.getLogger("last_wishes.memory")

# --------------------------------------------------------------------------- config


def _configure_environment() -> None:
    """Set Cognee env vars before ``import cognee`` (its settings read env at import)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:  # pragma: no cover
        pass

    env = os.environ
    # Project-local, gitignored storage (.gitignore has `.cognee*/`), so memory
    # survives a process restart.
    env.setdefault("SYSTEM_ROOT_DIRECTORY", str(PROJECT_ROOT / ".cognee_system"))
    env.setdefault("DATA_ROOT_DIRECTORY", str(PROJECT_ROOT / ".cognee_data"))
    env.setdefault("CACHE_ROOT_DIRECTORY", str(PROJECT_ROOT / ".cognee_cache"))
    # One shared graph/vector store: add_data_points (no dataset context) and
    # search() then see the same graph.
    env.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
    # Ladybug (Cognee's default graph DB) needs Homebrew openssl@3 on macOS; turso
    # (pyturso, the `cognee[turso]` extra) is pure-wheel and works everywhere.
    env.setdefault("GRAPH_DATABASE_PROVIDER", "turso")
    # Local embeddings, no API key: fastembed ships with cognee.
    env.setdefault("EMBEDDING_PROVIDER", "fastembed")
    env.setdefault("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    env.setdefault("EMBEDDING_DIMENSIONS", "384")
    env.setdefault("LOG_LEVEL", "ERROR")
    env.setdefault("TELEMETRY_DISABLED", "true")

    _apply_llm_env()


def _apply_llm_env() -> None:
    """Cognee reads LLM_PROVIDER / LLM_MODEL / LLM_API_KEY. Accept ANTHROPIC_API_KEY as a
    fallback so one key in .env is enough."""
    env = os.environ
    if not env.get("LLM_API_KEY") and env.get("ANTHROPIC_API_KEY"):
        env["LLM_API_KEY"] = env["ANTHROPIC_API_KEY"]
        env.setdefault("LLM_PROVIDER", "anthropic")
    key = env.get("LLM_API_KEY", "")
    if key.startswith("sk-ant") and not env.get("LLM_PROVIDER"):
        env["LLM_PROVIDER"] = "anthropic"
    if env.get("LLM_PROVIDER") == "anthropic":
        env.setdefault("LLM_MODEL", DEFAULT_ANTHROPIC_MODEL)


def llm_available() -> bool:
    return bool(os.environ.get("LLM_API_KEY", "").strip())


def _cognify_enabled() -> bool:
    flag = os.environ.get("LW_COGNIFY", "auto").lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return llm_available()


def _stub_unloadable_kuzu() -> None:
    """Cognee's relational migration chain does a top-level ``import kuzu`` (a shim over
    ladybug). If ladybug's native lib can't load (no openssl@3), that import kills
    ``setup()`` even though the migration body is a no-op with access control off.
    Register an empty stand-in so it imports; the turso graph backend never uses it."""
    if os.environ.get("GRAPH_DATABASE_PROVIDER", "").lower() in ("ladybug", "kuzu"):
        return
    try:
        import kuzu  # noqa: F401
    except Exception:
        for name in [m for m in sys.modules if m == "kuzu" or m.startswith(("kuzu.", "ladybug"))]:
            del sys.modules[name]
        sys.modules["kuzu"] = types.ModuleType("kuzu")


_configure_environment()
_stub_unloadable_kuzu()
_env_before_cognee = {k: v for k, v in os.environ.items() if v}

import cognee  # noqa: E402

# `import cognee` re-loads the project .env with override=True, so an empty line such as
# `LLM_API_KEY=` would wipe a key exported in the shell (or mapped from
# ANTHROPIC_API_KEY above). Put non-empty values back, then redo the LLM mapping.
for _k, _v in _env_before_cognee.items():
    if not os.environ.get(_k):
        os.environ[_k] = _v
_apply_llm_env()
try:
    from cognee.infrastructure.llm.config import get_llm_config as _get_llm_config

    _get_llm_config.cache_clear()
except Exception:  # pragma: no cover
    pass
from cognee import SearchType  # noqa: E402
from cognee.infrastructure.engine import DataPoint  # noqa: E402
from cognee.tasks.storage import add_data_points  # noqa: E402

# ----------------------------------------------------------------- graph models (§11)


class _Node(DataPoint):
    """Common fields: ``name`` is the display label, ``text`` is embedded for search."""

    name: str = ""
    text: str = ""


class Document(_Node):
    source_id: str
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["source_id"]}


class Wish(_Node):
    wish_id: str
    kind: str = ""
    source_id: str = ""
    stated_by: str = ""
    SOURCED_FROM: Optional[Document] = None
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["wish_id"]}


class Person(_Node):
    role: str = "parent"
    STATED: list[Wish] = []
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["name"]}


class Role(_Node):
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["name"]}


class FamilyMember(_Node):
    relation: str = ""
    HAS_ROLE: Optional[Role] = None
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["name"]}


class LineItem(_Node):
    item_id: str
    quote_id: str
    provider: str = ""
    category: str = ""
    price_type: str = "unknown"
    amount_low: Optional[float] = None
    amount_high: Optional[float] = None
    excerpt: str = ""
    source_doc: str = ""
    status: str = "listed"  # listed | unlisted (asked about, absent from the quote)
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["quote_id", "item_id"]}


class Quote(_Node):
    quote_id: str
    provider: str = ""
    quote_version: int = 1
    CONTAINS: list[LineItem] = []
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["quote_id"]}


class Provider(_Node):
    code: str
    fictional: bool = True
    OFFERS: list[Quote] = []
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["code"]}


class Question(_Node):
    question_id: str
    quote_id: str = ""
    item_name: str = ""
    status: str = "pending"  # pending | answered
    answered_by: str = ""
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["question_id"]}


class Reply(_Node):
    reply_id: str
    question_id: str = ""
    new_quote_id: str = ""
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["reply_id"]}


class Plan(_Node):
    plan_id: str
    quote_id: str = ""
    known_total: Optional[float] = None
    estimated_low: Optional[float] = None
    estimated_high: Optional[float] = None
    unresolved: list[str] = []
    wishes_satisfied: list[str] = []
    metadata: dict = {"index_fields": ["text"], "identity_fields": ["plan_id"]}


DOMAIN_TYPES = {
    c.__name__
    for c in (Document, Wish, Person, Role, FamilyMember, LineItem, Quote, Provider,
              Question, Reply, Plan)
}
_INTERNAL_PROPS = {
    "created_at", "updated_at", "ontology_valid", "ontology_uri", "version", "topological_rank",
    "metadata", "source_pipeline", "source_task", "source_node_set", "source_user",
    "source_content_hash", "feedback_weight", "importance_weight", "vector_distance",
}

# ------------------------------------------------------------- background event loop

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()
_setup_done = False


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            t = threading.Thread(target=_loop.run_forever, name="cognee-mem-loop", daemon=True)
            t.start()
        return _loop


def _run(coro: Coroutine[Any, Any, Any], timeout: float = 900) -> Any:
    """Run ``coro`` on the private loop and block for its result. Works from plain
    sync code and from inside a running event loop (Streamlit, Jupyter)."""
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result(timeout)


async def _ensure_setup() -> None:
    global _setup_done
    if not _setup_done:
        from cognee.modules.engine.operations.setup import setup

        import contextlib

        with contextlib.redirect_stdout(sys.stderr):  # cognee prints migration chatter
            await setup()
        _setup_done = True


async def _graph():
    from cognee.infrastructure.databases.graph import get_graph_engine

    return await get_graph_engine()


# ------------------------------------------------------------------------- helpers


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "item"


def _money(v: Optional[float]) -> str:
    return "unknown" if v is None else f"${v:,.0f}"


def _price_text(price_type: str, lo: Optional[float], hi: Optional[float]) -> str:
    if price_type == "unknown" or (lo is None and hi is None):
        return "price unknown"
    if price_type == "starting_at":
        return f"starting at {_money(lo)}"
    if lo is not None and hi is not None and lo != hi:
        return f"{price_type} {_money(lo)}-{_money(hi)}"
    return f"{price_type} {_money(lo if lo is not None else hi)}"


def _edge(src, rel: str, tgt, text: str) -> tuple:
    return (str(src), str(tgt), rel, {"relationship_name": rel, "relationship_type": rel,
                                      "edge_text": text})


async def _get_props(node_id) -> Optional[dict]:
    g = await _graph()
    node = await g.get_node(str(node_id))
    return dict(node) if node else None


async def _write(points: list, edges: Optional[list] = None) -> None:
    await _ensure_setup()
    await add_data_points(points, custom_edges=edges or None)


def _provider_code(provider: str) -> str:
    p = provider.strip()
    return p[len("provider "):].strip() if p.lower().startswith("provider ") else p


def _provider_node(provider: str) -> Provider:
    code = _provider_code(provider)
    return Provider(code=code, name=f"Provider {code}",
                    text=f"Provider {code} (fictional funeral provider)")


_semantic_lock: Optional[asyncio.Lock] = None
_semantic_tasks: list = []
_semantic_errors: list[str] = []


async def _add_semantic(text: str, node_set: list[str]) -> Optional[str]:
    """add + cognify the raw text (needs an LLM). Returns an error string or None."""
    global _semantic_lock
    if not _cognify_enabled():
        return "skipped (no LLM_API_KEY or LW_COGNIFY=0)"
    if _semantic_lock is None:
        _semantic_lock = asyncio.Lock()
    async with _semantic_lock:  # one cognify at a time
        try:
            await cognee.add(text, dataset_name=DATASET, node_set=node_set)
            await cognee.cognify(datasets=[DATASET])
            return None
        except Exception as e:  # keep the structured graph usable even if the LLM fails
            log.warning("cognify failed: %s", e)
            _semantic_errors.append(f"{type(e).__name__}: {e}")
            return f"failed: {type(e).__name__}: {e}"


def _schedule_semantic(text: str, node_set: list[str]) -> None:
    """Run add+cognify on the memory loop without blocking the caller (cognify takes
    tens of seconds per call). ``wait_for_semantic()`` joins them."""
    _semantic_tasks.append(asyncio.ensure_future(_add_semantic(text, node_set)))


async def _a_wait_semantic() -> list:
    pending = list(_semantic_tasks)
    _semantic_tasks.clear()
    return [await t for t in pending]


def wait_for_semantic() -> dict:
    """Block until queued add+cognify jobs finish. Returns their outcomes."""
    results = _run(_a_wait_semantic())
    return {"jobs": len(results), "errors": [r for r in results if r]}


# ------------------------------------------------------------------ write API (§9)


async def _a_remember_wish(text, source_id, wish_id, stated_by, source_text, cognify, kind,
                           confirmed_by):
    await _ensure_setup()
    g = await _graph()
    if wish_id is None:
        nodes, _ = await g.get_graph_data()
        wishes = [p for _, p in nodes if p.get("type") == "Wish"]
        for p in wishes:
            if p.get("text", "").strip().lower() == text.strip().lower():
                return p["wish_id"]
        nums = [int(m.group(1)) for p in wishes if (m := re.fullmatch(r"W(\d+)", p.get("wish_id", "")))]
        wish_id = f"W{max(nums, default=0) + 1}"

    doc = Document(source_id=source_id, name=source_id,
                   text=source_text or f"Source {source_id}: \"{text}\"")
    wish = Wish(wish_id=wish_id, name=f"{wish_id}: {text[:60]}", text=text, kind=kind or "",
                source_id=source_id, stated_by=stated_by, SOURCED_FROM=doc)
    person = Person(name=stated_by, text=f"{stated_by}, whose funeral wishes are recorded",
                    STATED=[wish])
    await _write([person])
    if confirmed_by:
        await _a_remember_confirmation(confirmed_by, [wish_id], "daughter", "Reviewer", source_id)
    if cognify is None:
        cognify = _cognify_enabled()
    if cognify:
        _schedule_semantic(f"{stated_by} wished: {text} (source {source_id}, wish {wish_id})",
                           ["wishes", wish_id])
    return wish_id


def remember_wish(text: str, source_id: str, *, wish_id: str | None = None,
                  stated_by: str = "Linda", source_text: str | None = None,
                  kind: str | None = None, confirmed_by: str | None = None,
                  cognify: bool | None = None) -> str:
    """Store one wish: Person(stated_by) -STATED-> Wish -SOURCED_FROM-> Document(source_id).

    Returns the wish id (e.g. "W3"); pass ``wish_id`` to fix it, otherwise the next free
    W<n> is used (re-remembering identical text returns the existing id). The same id is
    what ``Plan.wishes_satisfied`` and ``recall(exclude_wish_ids=...)`` use. The Cognee
    node UUID is ``Wish.id_for(wish_id)``. ``confirmed_by`` (e.g. "daughter") also writes
    FamilyMember -CONFIRMED-> Wish. ``cognify`` defaults to on when an LLM key is set: the
    raw text is queued for cognee.add + cognee.cognify in the background (call
    ``wait_for_semantic()`` to join); pass False to skip.
    """
    return _run(_a_remember_wish(text, source_id, wish_id, stated_by, source_text, cognify,
                                 kind, confirmed_by))


async def _a_remember_confirmation(member, wish_ids, relation, role, source_id):
    await _ensure_setup()
    fm = FamilyMember(name=member, relation=relation,
                      text=f"{member} ({relation} of Linda), the family's {role.lower()}",
                      HAS_ROLE=Role(name=role, text=f"{role}: reviews and approves the plan"))
    edges = []
    for wid in wish_ids:
        wprops = await _get_props(Wish.id_for(wid))
        if not wprops:
            raise KeyError(f"unknown wish {wid}")
        edges.append(_edge(fm.id, "CONFIRMED", Wish.id_for(wid),
                           f"{member} confirmed wish {wid}: {wprops.get('text', '')}"
                           + (f" (source {source_id})" if source_id else "")))
    await _write([fm], edges)
    return str(fm.id)


def remember_confirmation(member: str, wish_ids: list[str], *, relation: str = "daughter",
                          role: str = "Reviewer", source_id: str | None = None) -> str:
    """FamilyMember(member) -CONFIRMED-> Wish (each id), FamilyMember -HAS_ROLE-> Role."""
    return _run(_a_remember_confirmation(member, wish_ids, relation, role, source_id))


def _line_item_node(it: dict, quote_id: str, provider_code: str) -> LineItem:
    price = _price_text(it.get("price_type", "unknown"), it.get("amount_low"), it.get("amount_high"))
    return LineItem(
        item_id=it["item_id"], quote_id=quote_id, provider=provider_code,
        name=it.get("name", it["item_id"]), category=it.get("category", ""),
        price_type=it.get("price_type", "unknown"),
        amount_low=it.get("amount_low"), amount_high=it.get("amount_high"),
        excerpt=it.get("excerpt", ""), source_doc=it.get("source_doc", ""),
        text=(f"{it.get('name', '')} in quote {quote_id} from Provider {provider_code}: "
              f"{price}, category {it.get('category', '')}. Excerpt: \"{it.get('excerpt', '')}\""),
    )


async def _a_remember_quote(quote_id, provider, version, items, supersedes):
    await _ensure_setup()
    code = _provider_code(provider)
    li = [_line_item_node(dict(it), quote_id, code) for it in items]
    names = ", ".join(f"{x.name} ({_price_text(x.price_type, x.amount_low, x.amount_high)})"
                      for x in li)
    quote = Quote(quote_id=quote_id, provider=code, quote_version=int(version),
                  name=f"Quote {quote_id}",
                  text=(f"Quote {quote_id} (version {version}) from Provider {code}"
                        + (f", supersedes {supersedes}" if supersedes else "")
                        + f". Line items: {names or 'none'}"),
                  CONTAINS=li)
    prov = _provider_node(code)
    prov.OFFERS = [quote]
    edges = []
    if supersedes:
        old_id = Quote.id_for(supersedes)
        if not await _get_props(old_id):
            raise KeyError(f"quote {supersedes} (superseded) is not in memory")
        edges.append(_edge(quote.id, "SUPERSEDES", old_id,
                           f"Quote {quote_id} supersedes quote {supersedes}; {supersedes} is kept"))
    await _write([prov], edges)


def remember_quote(quote_id: str, provider: str, version: int, items: list[dict],
                   supersedes: str | None = None) -> None:
    """Provider -OFFERS-> Quote -CONTAINS-> LineItem; Quote(v2) -SUPERSEDES-> Quote(v1).
    The superseded quote is kept untouched."""
    _run(_a_remember_quote(quote_id, provider, version, items, supersedes))


async def _quote_items(quote_id: str) -> list[dict]:
    g = await _graph()
    out = []
    for src, rel, tgt in await g.get_connections(str(Quote.id_for(quote_id))):
        if rel.get("relationship_name") in ("CONTAINS", "OMITS") and tgt.get("type") == "LineItem" \
                and str(src.get("id")) == str(Quote.id_for(quote_id)):
            out.append(dict(tgt))
    return out


def _match_item(items: list[dict], item_name: str) -> Optional[dict]:
    want = item_name.strip().lower()
    for it in items:
        if it.get("name", "").strip().lower() == want:
            return it
    for it in items:
        n = it.get("name", "").lower()
        if want in n or (n and n in want):
            return it
    want_words = set(re.findall(r"[a-z]+", want)) - {"fee", "charge", "the", "a", "of"}
    for it in items:
        if want_words and want_words <= set(re.findall(r"[a-z]+", it.get("name", "").lower())):
            return it
    return None


async def _a_remember_question(question_id, quote_id, item_name, text):
    await _ensure_setup()
    qprops = await _get_props(Quote.id_for(quote_id))
    if not qprops:
        raise KeyError(f"quote {quote_id} is not in memory; call remember_quote first")
    code = qprops.get("provider", "")
    points, edges = [], []
    item = _match_item(await _quote_items(quote_id), item_name)
    if item:
        item_node_id = item["id"]
    else:  # the quote never listed it (e.g. A's crematory fee): unresolved placeholder
        ph = LineItem(item_id=f"{quote_id}:unlisted:{_slug(item_name)}", quote_id=quote_id,
                      provider=code, name=item_name, price_type="unknown", status="unlisted",
                      text=f"{item_name}: not listed in quote {quote_id} from Provider {code}; "
                           f"price unresolved")
        points.append(ph)
        item_node_id = ph.id
        edges.append(_edge(Quote.id_for(quote_id), "OMITS", ph.id,
                           f"Quote {quote_id} does not list {item_name}"))
    q = Question(question_id=question_id, quote_id=quote_id, item_name=item_name,
                 status="pending", name=f"Question {question_id}",
                 text=text or (f"Pending clarification question {question_id} to Provider {code} "
                               f"about {item_name} in quote {quote_id} (unresolved)"))
    points.append(q)
    edges += [
        _edge(q.id, "ABOUT", item_node_id, f"Question {question_id} is about {item_name}"),
        _edge(q.id, "REGARDING", Quote.id_for(quote_id),
              f"Question {question_id} concerns quote {quote_id}"),
        _edge(q.id, "ASKED_OF", Provider.id_for(code),
              f"Question {question_id} was asked of Provider {code}"),
    ]
    await _write(points, edges)


def remember_question(question_id: str, quote_id: str, item_name: str,
                      text: str | None = None) -> None:
    """Question -ABOUT-> LineItem (status pending). If the quote never listed the item,
    an 'unlisted' LineItem is created and linked Quote -OMITS-> it. Also
    Question -REGARDING-> Quote and Question -ASKED_OF-> Provider."""
    _run(_a_remember_question(question_id, quote_id, item_name, text))


async def _a_remember_reply(reply_id, question_id, new_quote_id, text):
    await _ensure_setup()
    qprops = await _get_props(Question.id_for(question_id))
    if not qprops:
        raise KeyError(f"question {question_id} is not in memory")
    if not await _get_props(Quote.id_for(new_quote_id)):
        raise KeyError(f"quote {new_quote_id} is not in memory; call remember_quote first")
    q = Question(**{k: qprops[k] for k in ("question_id", "quote_id", "item_name", "name", "text")
                    if k in qprops})
    q.status = "answered"
    q.answered_by = reply_id
    q.text = re.sub(r"^Pending", "Answered", q.text)
    r = Reply(reply_id=reply_id, question_id=question_id, new_quote_id=new_quote_id,
              name=f"Reply {reply_id}",
              text=text or (f"Reply {reply_id} answers question {question_id} about "
                            f"{qprops.get('item_name')} and produced quote {new_quote_id}"))
    edges = [
        _edge(r.id, "ANSWERS", q.id, f"Reply {reply_id} answers question {question_id}"),
        _edge(r.id, "PRODUCED", Quote.id_for(new_quote_id),
              f"Reply {reply_id} produced quote {new_quote_id}"),
    ]
    item = _match_item(await _quote_items(new_quote_id), qprops.get("item_name", ""))
    if item:
        edges.append(_edge(r.id, "RESOLVES", item["id"],
                           f"Reply {reply_id} sets {item.get('name')} at "
                           f"{_price_text(item.get('price_type', ''), item.get('amount_low'), item.get('amount_high'))}"))
    await _write([q, r], edges)


def remember_reply(reply_id: str, question_id: str, new_quote_id: str,
                   text: str | None = None) -> None:
    """Reply -ANSWERS-> Question (marked answered), Reply -PRODUCED-> Quote(new), and
    Reply -RESOLVES-> the new quote's matching LineItem when there is one."""
    _run(_a_remember_reply(reply_id, question_id, new_quote_id, text))


async def _a_remember_plan(plan):
    await _ensure_setup()
    qid = plan["quote_id"]
    if not await _get_props(Quote.id_for(qid)):
        raise KeyError(f"quote {qid} is not in memory")
    p = Plan(plan_id=plan["plan_id"], quote_id=qid, name=f"Plan {plan['plan_id']}",
             known_total=plan.get("known_total"), estimated_low=plan.get("estimated_low"),
             estimated_high=plan.get("estimated_high"),
             unresolved=list(plan.get("unresolved") or []),
             wishes_satisfied=list(plan.get("wishes_satisfied") or []),
             text=(f"Plan {plan['plan_id']} based on quote {qid}: known total "
                   f"{_money(plan.get('known_total'))}, estimated "
                   f"{_money(plan.get('estimated_low'))}-{_money(plan.get('estimated_high'))}; "
                   f"unresolved: {', '.join(plan.get('unresolved') or []) or 'none'}; "
                   f"honors wishes {', '.join(plan.get('wishes_satisfied') or []) or 'none'}"))
    edges = [_edge(p.id, "BASED_ON", Quote.id_for(qid), f"Plan {p.plan_id} is based on quote {qid}")]
    for wid in plan.get("wishes_satisfied") or []:
        if await _get_props(Wish.id_for(wid)):
            edges.append(_edge(p.id, "HONORS", Wish.id_for(wid), f"Plan {p.plan_id} honors wish {wid}"))
    await _write([p], edges)


def remember_plan(plan: dict) -> None:
    """Plan -BASED_ON-> Quote; Plan -HONORS-> Wish for each id in wishes_satisfied."""
    _run(_a_remember_plan(plan))


# ---------------------------------------------------------------------- read API


def _clean_node(node_id: str, props: dict, via: str | None = None) -> dict:
    t = props.get("type", "")
    clean = {k: v for k, v in props.items()
             if k not in _INTERNAL_PROPS and k not in ("id", "type") and v not in (None, "", [])}
    label = props.get("name") or props.get("text", "")[:60] or t
    out = {"id": str(node_id), "type": t, "label": label, "props": clean}
    if via:
        out["via"] = via
    return out


def _clean_edge(src: str, tgt: str, rel: str, props: dict, via: str | None = None,
                labels: dict | None = None) -> dict:
    out = {"source": str(src), "target": str(tgt), "relationship": rel,
           "text": props.get("edge_text", "")}
    if labels:
        out["source_label"] = labels.get(str(src), "")
        out["target_label"] = labels.get(str(tgt), "")
    if via:
        out["via"] = via
    vd = props.get("vector_distance")
    if isinstance(vd, list) and vd and vd[0] is not None:
        out["vector_distance"] = round(float(vd[0]), 4)
    return out


async def _a_graph_snapshot(include_semantic: bool) -> dict:
    await _ensure_setup()
    g = await _graph()
    nodes, edges = await g.get_graph_data()
    keep = {str(nid) for nid, p in nodes
            if include_semantic or p.get("type") in DOMAIN_TYPES}
    out_nodes = [_clean_node(nid, p) for nid, p in nodes if str(nid) in keep]
    labels = {n["id"]: n["label"] for n in out_nodes}
    out_edges = [_clean_edge(s, t, r, p, labels=labels) for s, t, r, p in edges
                 if str(s) in keep and str(t) in keep]
    return {"nodes": out_nodes, "edges": out_edges}


def graph_snapshot(include_semantic: bool = False) -> dict:
    """Every node/edge currently in Cognee's graph store (for before/after views).
    By default only the §11 domain types; ``include_semantic=True`` adds cognify's
    chunks/entities too."""
    return _run(_a_graph_snapshot(include_semantic))


def _is_excluded(props: dict, excluded_ids: set[str], excluded_wish_ids: set[str],
                 excluded_texts: list[str]) -> bool:
    if str(props.get("id")) in excluded_ids:
        return True
    bts = props.get("belongs_to_set") or []
    if isinstance(bts, str):
        bts = [bts]
    names = {b.get("name") if isinstance(b, dict) else str(b) for b in bts}
    if names & excluded_wish_ids:
        return True
    if props.get("type") not in DOMAIN_TYPES and excluded_texts:
        blob = " ".join(str(props.get(k, "")) for k in ("name", "text", "description")).lower()
        for t in excluded_texts:
            if t and (t in blob or (props.get("name") and str(props["name"]).lower() in t
                                    and len(str(props["name"])) > 6)):
                return True
    return False


_ANSWER_SYSTEM_PROMPT = (
    "You are the memory of a family's funeral-planning assistant. Answer the question using "
    "ONLY the knowledge-graph context given (nodes and relationships). Be calm, plain and brief "
    "(at most 4 sentences). Mention any pending questions and the relevant wishes of the "
    "deceased by id when they bear on the question. Never invent prices, never call anything "
    "illegal, never claim anything was purchased. If the context does not answer, say so."
)


def _context_text(nodes: list[dict], edges: list[dict]) -> str:
    lines = ["Nodes:"]
    for n in nodes:
        p = n["props"]
        lines.append(f"- [{n['type']}] {n['label']}: {p.get('text', '')}"
                     + (f" (status: {p['status']})" if p.get("status") else ""))
    lines.append("Relationships:")
    for e in edges:
        lines.append(f"- {e.get('source_label', e['source'])} --{e['relationship']}--> "
                     f"{e.get('target_label', e['target'])}" + (f"  ({e['text']})" if e.get("text") else ""))
    return "\n".join(lines)


def _graph_only_answer(nodes: list[dict], excluded: list[str]) -> str:
    pending = [n for n in nodes if n["type"] == "Question" and n["props"].get("status") == "pending"]
    answered = [n for n in nodes if n["type"] == "Question" and n["props"].get("status") == "answered"]
    wishes = [n for n in nodes if n["type"] == "Wish"]
    parts = []
    if pending:
        parts.append("Pending: " + "; ".join(
            f"{n['props'].get('question_id')} about {n['props'].get('item_name')} "
            f"(quote {n['props'].get('quote_id')})" for n in pending) + ".")
    if answered:
        parts.append("Answered: " + "; ".join(
            f"{n['props'].get('question_id')} about {n['props'].get('item_name')} "
            f"(by {n['props'].get('answered_by')})" for n in answered) + ".")
    if wishes:
        parts.append("Wishes on record: " + "; ".join(
            f"{n['props'].get('wish_id')} \"{n['props'].get('text')}\" "
            f"({n['props'].get('stated_by')}, source {n['props'].get('source_id')})"
            for n in wishes) + ".")
    if excluded:
        parts.append(f"(Counterfactual: wishes {', '.join(excluded)} withheld from memory.)")
    return " ".join(parts) or "Nothing relevant found in memory."


async def _a_recall(query: str, exclude_wish_ids: list[str] | None, top_k: int,
                    standing_context: bool, use_llm: bool | None) -> dict:
    await _ensure_setup()
    g = await _graph()
    excluded_w = set(exclude_wish_ids or [])
    excluded_ids = {str(Wish.id_for(w)) for w in excluded_w}
    excluded_texts = []
    for w in excluded_w:
        p = await _get_props(Wish.id_for(w))
        if p and p.get("text"):
            excluded_texts.append(p["text"].lower())

    # 1. Cognee graph retrieval (embedding-based triplet search, no LLM call).
    search_error = None
    raw_edges = []
    try:
        res = await cognee.search(query_text=query, query_type=SearchType.GRAPH_COMPLETION,
                                  only_context=True, verbose=True, top_k=top_k)
        for r in res or []:
            objs = r.get("objects_result") if isinstance(r, dict) else getattr(r, "objects_result", None)
            raw_edges.extend(objs or [])
    except Exception as e:  # empty graph etc.
        search_error = f"{type(e).__name__}: {e}"

    node_props: dict[str, dict] = {}
    node_via: dict[str, str] = {}
    edges: list[tuple] = []  # (src, tgt, rel, props, via)
    seen_edges = set()
    dropped = 0
    for e in raw_edges:
        s, t = str(e.node1.id), str(e.node2.id)
        rel = e.attributes.get("relationship_name") or e.attributes.get("relationship_type") or ""
        ps = {**e.node1.attributes, "id": s}
        pt = {**e.node2.attributes, "id": t}
        if _is_excluded(ps, excluded_ids, excluded_w, excluded_texts) or \
                _is_excluded(pt, excluded_ids, excluded_w, excluded_texts):
            dropped += 1
            continue
        key = (s, t, rel)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append((s, t, rel, dict(e.attributes), "cognee_search"))
        for nid in (s, t):
            node_via.setdefault(nid, "cognee_search")

    # 2. Standing context: wishes + open questions, read from the same Cognee graph.
    if standing_context:
        all_nodes, all_edges = await g.get_graph_data()
        props_by_id = {str(i): {**p, "id": str(i)} for i, p in all_nodes}
        standing = {i for i, p in props_by_id.items()
                    if (p.get("type") == "Wish" and i not in excluded_ids)
                    or (p.get("type") == "Question" and p.get("status") == "pending")}
        for i in standing:
            node_via.setdefault(i, "standing_context")
        for s, t, rel, p in all_edges:
            s, t = str(s), str(t)
            if (s in standing or t in standing) and (s, t, rel) not in seen_edges:
                other = t if s in standing else s
                if props_by_id.get(other, {}).get("type") not in DOMAIN_TYPES:
                    continue
                if other in excluded_ids:
                    continue
                seen_edges.add((s, t, rel))
                edges.append((s, t, rel, dict(p), "standing_context"))
                node_via.setdefault(other, "standing_context")

    # 3. Full node properties straight from Cognee's graph engine.
    ids = list(node_via)
    fetched = await g.get_nodes(ids) if ids else []
    for p in fetched or []:
        node_props[str(p.get("id"))] = dict(p)
    nodes = [_clean_node(i, node_props.get(i, {"id": i}), node_via[i]) for i in ids]
    labels = {n["id"]: n["label"] for n in nodes}
    out_edges = [_clean_edge(s, t, rel, p, via, labels) for s, t, rel, p, via in edges]

    # 4. Answer.
    answer_source = "graph_only"
    answer = None
    if use_llm is None:
        use_llm = llm_available()
    llm_error = None
    if use_llm:
        try:
            from cognee.infrastructure.llm.LLMGateway import LLMGateway

            answer = await LLMGateway.acreate_structured_output(
                text_input=f"Question: {query}\n\nContext:\n{_context_text(nodes, out_edges)}",
                system_prompt=_ANSWER_SYSTEM_PROMPT, response_model=str)
            answer_source = f"llm:{os.environ.get('LLM_MODEL', 'cognee-default')}"
        except Exception as e:
            llm_error = f"{type(e).__name__}: {e}"
    if not answer:
        answer = _graph_only_answer(nodes, sorted(excluded_w))

    return {
        "query": query,
        "answer": str(answer).strip(),
        "nodes": nodes,
        "edges": out_edges,
        "excluded_wish_ids": sorted(excluded_w),
        "meta": {
            "cognee_call": "cognee.search(query_type=SearchType.GRAPH_COMPLETION, "
                           "only_context=True, verbose=True)",
            "search_edges": sum(1 for e in out_edges if e["via"] == "cognee_search"),
            "standing_edges": sum(1 for e in out_edges if e["via"] == "standing_context"),
            "dropped_by_counterfactual": dropped,
            "answer_source": answer_source,
            **({"search_error": search_error} if search_error else {}),
            **({"llm_error": llm_error} if llm_error else {}),
        },
    }


def recall(query: str, *, exclude_wish_ids: list[str] | None = None, top_k: int = 20,
           standing_context: bool = True, use_llm: bool | None = None) -> dict:
    """Return {"query", "answer", "nodes", "edges", "excluded_wish_ids", "meta"}.

    nodes/edges are the real ones: edges Cognee's GRAPH_COMPLETION retrieval returned
    (``via="cognee_search"``) plus wishes / open questions read from Cognee's graph
    (``via="standing_context"``). ``exclude_wish_ids`` (e.g. ["W3"]) removes those wishes
    and anything derived from them before the answer is written: the counterfactual.
    """
    return _run(_a_recall(query, exclude_wish_ids, top_k, standing_context, use_llm))


def recall_counterfactual(query: str, exclude_wish_ids: list[str] = ("W3",)) -> dict:
    """Same query twice: with full memory and with ``exclude_wish_ids`` removed."""
    return {"with_memory": recall(query),
            "without": recall(query, exclude_wish_ids=list(exclude_wish_ids))}


async def _a_reset():
    global _setup_done
    await _a_wait_semantic()
    await _ensure_setup()
    await cognee.prune.prune_data()
    await cognee.prune.prune_system(graph=True, vector=True, metadata=True, cache=True)
    _setup_done = False


def reset_memory() -> None:
    """Delete everything Cognee holds for this project (for clean demo runs)."""
    _run(_a_reset())


# ------------------------------------------------------------------------- CLI

_SELFTEST_ITEMS_A = [
    {"item_id": "A-01", "quote_id": "A-v1", "provider": "A", "name": "Basic services of funeral director",
     "category": "basic_fee", "price_type": "fixed", "amount_low": 895.0, "amount_high": 895.0,
     "excerpt": "Basic services of funeral director and staff ... $895", "source_doc": "quote_A.txt",
     "confidence": 0.9},
    {"item_id": "A-02", "quote_id": "A-v1", "provider": "A", "name": "Transfer of remains",
     "category": "basic_fee", "price_type": "fixed", "amount_low": 350.0, "amount_high": 350.0,
     "excerpt": "Transfer of remains to funeral home ... $350", "source_doc": "quote_A.txt",
     "confidence": 0.9},
]
_SELFTEST_ITEMS_B = [
    {"item_id": "B-01", "quote_id": "B-v1", "provider": "B", "name": "Direct cremation (basic)",
     "category": "package", "price_type": "fixed", "amount_low": 1195.0, "amount_high": 1195.0,
     "excerpt": "Direct cremation ... $1,195", "source_doc": "quote_B.txt", "confidence": 0.93},
]


def _selftest() -> dict:
    reset_memory()
    w1 = remember_wish("Cremation, keep it simple", "wishes_linda.txt#1", wish_id="W1",
                       source_text="Keep it simple. Cremation, no public viewing. "
                                   "Please avoid unnecessary extras.")
    w2 = remember_wish("No public viewing", "wishes_linda.txt#2", wish_id="W2")
    w3 = remember_wish("Please avoid unnecessary extras", "wishes_linda.txt#3", wish_id="W3")
    remember_confirmation("Daughter", [w1, w2, w3], source_id="wishes_linda.txt#confirmation")
    remember_quote("A-v1", "A", 1, _SELFTEST_ITEMS_A)
    remember_quote("B-v1", "B", 1, _SELFTEST_ITEMS_B)
    remember_question("Q1", "A-v1", "crematory fee")
    semantic = wait_for_semantic()
    snap = graph_snapshot()
    return {"semantic_layer": semantic if llm_available() else "skipped (no LLM key)",
            "wishes": [w1, w2, w3], "nodes": len(snap["nodes"]), "edges": len(snap["edges"]),
            "relationships": sorted({e["relationship"] for e in snap["edges"]})}


def _main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "selftest":
        out = _selftest()
    elif cmd == "recall":
        out = recall(" ".join(rest) or "What was pending with Provider A?")
    elif cmd == "counterfactual":
        q = rest[0] if rest else "Should we choose Provider C's package with viewing and flowers?"
        out = recall_counterfactual(q, rest[1:] or ["W3"])
    elif cmd == "snapshot":
        out = graph_snapshot(include_semantic="--all" in rest)
    elif cmd == "reset":
        reset_memory()
        out = {"reset": True}
    else:
        print(f"unknown command {cmd!r}\n{__doc__}")
        return 2
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
