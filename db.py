"""Canonical state for Last Wishes (LAST_WISHES.md §10).

SingleStore is the real backend (SINGLESTORE_URL in .env). For tests and parallel
development, a local sqlite file is used when SINGLESTORE_URL is unset or LW_DB=sqlite.
The demo uses SingleStore.

Conventions
- All SQL is written with ``%s`` placeholders (singlestoredb paramstyle is
  ``pyformat``); they are rewritten to ``?`` for sqlite.
- Ids are strings (no AUTO_INCREMENT) so both backends behave identically.
- JSON fields are stored as JSON text in ``*_json`` columns and decoded by helpers.
- Timestamps are ISO-8601 UTC strings.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

log = logging.getLogger("last_wishes.db")

ROOT = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = ROOT / ".lw_dev.sqlite"

_local = threading.local()
_warned_sqlite = False


# --------------------------------------------------------------------------- backend
def backend() -> str:
    """'singlestore' or 'sqlite'."""
    if os.getenv("LW_DB", "").lower() == "sqlite" or not os.getenv("SINGLESTORE_URL"):
        return "sqlite"
    return "singlestore"


def _sqlite_path() -> str:
    return os.getenv("LW_SQLITE_PATH") or str(DEFAULT_SQLITE_PATH)


def _new_conn():
    global _warned_sqlite
    if backend() == "sqlite":
        if not _warned_sqlite:
            log.warning("DEV SQLITE BACKEND — not SingleStore (%s)", _sqlite_path())
            print(f"[db] DEV SQLITE BACKEND — not SingleStore ({_sqlite_path()})")
            _warned_sqlite = True
        conn = sqlite3.connect(_sqlite_path(), isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn
    import singlestoredb as s2

    # URL form: [scheme://]user:password@host:port/db_name  (see singlestoredb.connect docs)
    return s2.connect(os.environ["SINGLESTORE_URL"], results_type="dicts", autocommit=True)


def get_conn():
    """Thread-local cached connection for the current backend."""
    key = (backend(), os.getenv("SINGLESTORE_URL") if backend() == "singlestore" else _sqlite_path())
    cached = getattr(_local, "conn", None)
    if cached is not None and getattr(_local, "key", None) == key:
        return cached
    if cached is not None:
        try:
            cached.close()
        except Exception:
            pass
    _local.conn = _new_conn()
    _local.key = key
    return _local.conn


def close_conn() -> None:
    cached = getattr(_local, "conn", None)
    if cached is not None:
        try:
            cached.close()
        except Exception:
            pass
    _local.conn = None
    _local.key = None


def _sql(sql: str) -> str:
    return sql.replace("%s", "?") if backend() == "sqlite" else sql


def _run(sql: str, params: Iterable[Any] = (), fetch: bool = False):
    params = tuple(params)
    for attempt in (0, 1):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(_sql(sql), params)
            if fetch:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            return cur.rowcount
        except Exception as e:  # reconnect once on dropped SingleStore connections
            if attempt == 0 and backend() == "singlestore" and _is_connection_error(e):
                close_conn()
                continue
            raise
        finally:
            try:
                cur.close()
            except Exception:
                pass


def _is_connection_error(e: Exception) -> bool:
    try:
        import singlestoredb.exceptions as s2e
        return isinstance(e, (s2e.OperationalError, s2e.InterfaceError))
    except Exception:
        return False


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    """SELECT -> list of dict rows."""
    return _run(sql, params, fetch=True)


def query_one(sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """INSERT/UPDATE/DELETE -> affected row count."""
    return _run(sql, params, fetch=False)


def is_duplicate_error(e: Exception) -> bool:
    """True if e is a UNIQUE/PRIMARY KEY violation (MySQL errno 1062 / sqlite IntegrityError)."""
    if isinstance(e, sqlite3.IntegrityError):
        return True
    try:
        import singlestoredb.exceptions as s2e
        if isinstance(e, s2e.IntegrityError):
            return True
    except Exception:
        pass
    return bool(e.args) and e.args[0] == 1062


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(s: Optional[str], default: Any = None) -> Any:
    if s is None or s == "":
        return default
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- schema
def _vector_dim() -> Optional[int]:
    # TODO(vectors): set LW_VECTOR_DIM to the embedding size once the embedding model is fixed;
    # then excerpt_vec / text_vec are created as VECTOR(dim, F32) on SingleStore.
    v = os.getenv("LW_VECTOR_DIM")
    return int(v) if v and v.isdigit() else None


def _ddl() -> list[str]:
    s2 = backend() == "singlestore"
    dim = _vector_dim() if s2 else None
    excerpt_vec = f",\n  excerpt_vec VECTOR({dim}, F32)" if dim else ""
    text_vec = f",\n  text_vec VECTOR({dim}, F32)" if dim else ""
    T = "LONGTEXT" if s2 else "TEXT"
    # outbox: ROWSTORE + SHARD KEY(idempotency_key) so the UNIQUE/PRIMARY key on
    # idempotency_key is actually enforced cluster-wide (unique keys must contain the shard key).
    outbox_prefix = "CREATE ROWSTORE TABLE IF NOT EXISTS" if s2 else "CREATE TABLE IF NOT EXISTS"
    outbox_shard = ",\n  SHARD KEY (idempotency_key)" if s2 else ""
    return [
        f"""CREATE TABLE IF NOT EXISTS wishes (
  id VARCHAR(64) NOT NULL, text {T}, source_id VARCHAR(255), confirmed_by VARCHAR(255),
  confirmed_at VARCHAR(40), created_at VARCHAR(40),
  PRIMARY KEY (id))""",
        f"""CREATE TABLE IF NOT EXISTS documents (
  id VARCHAR(64) NOT NULL, kind VARCHAR(32), provider VARCHAR(64), filename VARCHAR(255),
  is_fictional TINYINT, source_url VARCHAR(1024), captured_at VARCHAR(40), raw_text {T},
  PRIMARY KEY (id))""",
        """CREATE TABLE IF NOT EXISTS quotes (
  id VARCHAR(64) NOT NULL, provider VARCHAR(64), version INT, supersedes_id VARCHAR(64),
  document_id VARCHAR(64), created_at VARCHAR(40),
  PRIMARY KEY (id))""",
        f"""CREATE TABLE IF NOT EXISTS line_items (
  id VARCHAR(64) NOT NULL, quote_id VARCHAR(64) NOT NULL, provider VARCHAR(64), name VARCHAR(512),
  category VARCHAR(32), price_type VARCHAR(32), amount_low DOUBLE, amount_high DOUBLE,
  excerpt {T}, source_doc VARCHAR(255), confidence DOUBLE{excerpt_vec},
  PRIMARY KEY (quote_id, id))""",
        f"""CREATE TABLE IF NOT EXISTS flags (
  id VARCHAR(64) NOT NULL, quote_id VARCHAR(64) NOT NULL, item_id VARCHAR(64), kind VARCHAR(32),
  excerpt {T}, reference {T}, message {T},
  PRIMARY KEY (quote_id, id))""",
        f"""CREATE TABLE IF NOT EXISTS plans (
  id VARCHAR(64) NOT NULL, quote_id VARCHAR(64), known_total DOUBLE, est_low DOUBLE, est_high DOUBLE,
  unresolved_json {T}, items_json {T}, not_needed_json {T}, wishes_satisfied_json {T},
  stale TINYINT, created_at VARCHAR(40),
  PRIMARY KEY (id))""",
        f"""CREATE TABLE IF NOT EXISTS approvals (
  id VARCHAR(64) NOT NULL, kind VARCHAR(32), quote_id VARCHAR(64), provider VARCHAR(64),
  recipient VARCHAR(512), body {T}, extra_json {T}, payload_hash CHAR(64), status VARCHAR(32),
  approved_by VARCHAR(255), persona_inquiry_id VARCHAR(255), created_at VARCHAR(40),
  approved_at VARCHAR(40), invalidated_at VARCHAR(40), invalid_reason {T},
  PRIMARY KEY (id))""",
        f"""{outbox_prefix} outbox (
  id VARCHAR(64) NOT NULL, approval_id VARCHAR(64) NOT NULL, idempotency_key CHAR(64) NOT NULL,
  kind VARCHAR(32), recipient VARCHAR(512), body {T}, status VARCHAR(32), attempts INT,
  display_status VARCHAR(255), last_error {T}, created_at VARCHAR(40), sent_at VARCHAR(40),
  PRIMARY KEY (idempotency_key){outbox_shard})""",
        f"""CREATE TABLE IF NOT EXISTS audit_log (
  id VARCHAR(64) NOT NULL, ts VARCHAR(40), actor VARCHAR(255), action VARCHAR(255), detail_json {T},
  PRIMARY KEY (id))""",
        f"""CREATE TABLE IF NOT EXISTS sie_calls (
  id VARCHAR(64) NOT NULL, ts VARCHAR(40), recipe VARCHAR(255), model VARCHAR(255),
  latency_ms INT, input_chars INT, output_json {T},
  PRIMARY KEY (id))""",
        f"""CREATE TABLE IF NOT EXISTS ftc_reference (
  id VARCHAR(64) NOT NULL, text {T}, url VARCHAR(1024){text_vec},
  PRIMARY KEY (id))""",
    ]


TABLES = ("wishes", "documents", "quotes", "line_items", "flags", "plans",
          "approvals", "outbox", "audit_log", "sie_calls", "ftc_reference")


def init_schema() -> None:
    """Create every §10 table (IF NOT EXISTS). Safe to call on every app start."""
    for stmt in _ddl():
        execute(stmt)


def reset_all() -> None:
    """Delete all rows from every table (keeps schema). For a clean demo run."""
    init_schema()
    for t in TABLES:
        execute(f"DELETE FROM {t}")


# --------------------------------------------------------------------------- documents
def insert_document(kind: str, provider: Optional[str], filename: str, raw_text: str, *,
                    is_fictional: bool = True, source_url: Optional[str] = None,
                    captured_at: Optional[str] = None, doc_id: Optional[str] = None) -> str:
    """kind e.g. 'quote' | 'reply' | 'price_list' | 'wish_note'. Returns document id."""
    doc_id = doc_id or new_id("doc")
    execute("INSERT INTO documents (id, kind, provider, filename, is_fictional, source_url, captured_at, raw_text) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (doc_id, kind, provider, filename, int(bool(is_fictional)), source_url, captured_at or now(), raw_text))
    return doc_id


def get_document(doc_id: str) -> Optional[dict]:
    row = query_one("SELECT * FROM documents WHERE id=%s", (doc_id,))
    if row:
        row["is_fictional"] = bool(row["is_fictional"])
    return row


def list_documents(kind: Optional[str] = None) -> list[dict]:
    if kind:
        rows = query("SELECT * FROM documents WHERE kind=%s ORDER BY captured_at", (kind,))
    else:
        rows = query("SELECT * FROM documents ORDER BY captured_at")
    for r in rows:
        r["is_fictional"] = bool(r["is_fictional"])
    return rows


# --------------------------------------------------------------------------- quotes
def insert_quote(provider: str, version: int, *, document_id: Optional[str] = None,
                 supersedes_id: Optional[str] = None, quote_id: Optional[str] = None) -> str:
    """Returns quote id (default '<provider>-v<version>', e.g. 'A-v2'). Old versions are kept."""
    quote_id = quote_id or f"{provider}-v{version}"
    execute("INSERT INTO quotes (id, provider, version, supersedes_id, document_id, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (quote_id, provider, int(version), supersedes_id, document_id, now()))
    return quote_id


def get_quote(quote_id: str) -> Optional[dict]:
    return query_one("SELECT * FROM quotes WHERE id=%s", (quote_id,))


def list_quotes(latest_only: bool = False, provider: Optional[str] = None) -> list[dict]:
    """All quote rows ordered by provider, version. latest_only -> one row per provider."""
    if provider:
        rows = query("SELECT * FROM quotes WHERE provider=%s ORDER BY provider, version", (provider,))
    else:
        rows = query("SELECT * FROM quotes ORDER BY provider, version")
    if latest_only:
        latest: dict[str, dict] = {}
        for r in rows:
            latest[r["provider"]] = r  # ordered by version asc -> last wins
        rows = list(latest.values())
    return rows


def latest_quote_version(provider: str) -> Optional[dict]:
    """Latest quote row for a provider (highest version), or None."""
    return query_one("SELECT * FROM quotes WHERE provider=%s ORDER BY version DESC LIMIT 1", (provider,))


def next_quote_version(provider: str) -> int:
    q = latest_quote_version(provider)
    return (int(q["version"]) + 1) if q else 1


# --------------------------------------------------------------------------- line items
def insert_line_items(items: list[dict]) -> int:
    """Insert LineItem dicts (contracts.LineItem). Returns count."""
    for it in items:
        execute("INSERT INTO line_items (id, quote_id, provider, name, category, price_type, amount_low, "
                "amount_high, excerpt, source_doc, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (it["item_id"], it["quote_id"], it.get("provider"), it.get("name"), it.get("category"),
                 it.get("price_type"), it.get("amount_low"), it.get("amount_high"), it.get("excerpt"),
                 it.get("source_doc"), it.get("confidence")))
    return len(items)


def _row_to_item(r: dict) -> dict:
    return {
        "item_id": r["id"], "quote_id": r["quote_id"], "provider": r.get("provider"), "name": r.get("name"),
        "category": r.get("category"), "price_type": r.get("price_type"),
        "amount_low": None if r.get("amount_low") is None else float(r["amount_low"]),
        "amount_high": None if r.get("amount_high") is None else float(r["amount_high"]),
        "excerpt": r.get("excerpt"), "source_doc": r.get("source_doc"),
        "confidence": None if r.get("confidence") is None else float(r["confidence"]),
    }


def get_quote_items(quote_id: str) -> list[dict]:
    """LineItem dicts for one quote version, ordered by item_id."""
    rows = query("SELECT id, quote_id, provider, name, category, price_type, amount_low, amount_high, "
                 "excerpt, source_doc, confidence FROM line_items WHERE quote_id=%s ORDER BY id", (quote_id,))
    return [_row_to_item(r) for r in rows]


# --------------------------------------------------------------------------- flags
def insert_flags(flags: list[dict]) -> int:
    """Insert Flag dicts (contracts.Flag). Returns count."""
    for f in flags:
        execute("INSERT INTO flags (id, quote_id, item_id, kind, excerpt, reference, message) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (f["flag_id"], f["quote_id"], f.get("item_id"), f.get("kind"), f.get("excerpt"),
                 f.get("reference"), f.get("message")))
    return len(flags)


def list_flags(quote_id: Optional[str] = None) -> list[dict]:
    if quote_id:
        rows = query("SELECT * FROM flags WHERE quote_id=%s ORDER BY id", (quote_id,))
    else:
        rows = query("SELECT * FROM flags ORDER BY quote_id, id")
    return [{"flag_id": r["id"], "quote_id": r["quote_id"], "item_id": r.get("item_id"), "kind": r.get("kind"),
             "excerpt": r.get("excerpt"), "reference": r.get("reference"), "message": r.get("message")}
            for r in rows]


def delete_flags(quote_id: str) -> int:
    """Clear flags for a quote before re-running rules on it."""
    return execute("DELETE FROM flags WHERE quote_id=%s", (quote_id,))


# --------------------------------------------------------------------------- plans
def upsert_plan(plan: dict, stale: bool = False) -> str:
    """Insert or replace a Plan (contracts.Plan) by plan_id. Returns plan_id."""
    execute("DELETE FROM plans WHERE id=%s", (plan["plan_id"],))
    execute("INSERT INTO plans (id, quote_id, known_total, est_low, est_high, unresolved_json, items_json, "
            "not_needed_json, wishes_satisfied_json, stale, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (plan["plan_id"], plan["quote_id"], plan.get("known_total"), plan.get("estimated_low"),
             plan.get("estimated_high"), dumps(plan.get("unresolved", [])), dumps(plan.get("items", [])),
             dumps(plan.get("not_needed", [])), dumps(plan.get("wishes_satisfied", [])), int(bool(stale)), now()))
    return plan["plan_id"]


def _row_to_plan(r: dict) -> dict:
    return {
        "plan_id": r["id"], "quote_id": r["quote_id"],
        "items": loads(r.get("items_json"), []),
        "known_total": None if r.get("known_total") is None else float(r["known_total"]),
        "estimated_low": None if r.get("est_low") is None else float(r["est_low"]),
        "estimated_high": None if r.get("est_high") is None else float(r["est_high"]),
        "unresolved": loads(r.get("unresolved_json"), []),
        "not_needed": loads(r.get("not_needed_json"), []),
        "wishes_satisfied": loads(r.get("wishes_satisfied_json"), []),
        "stale": bool(r.get("stale")), "created_at": r.get("created_at"),
    }


def get_plan(plan_id: str) -> Optional[dict]:
    r = query_one("SELECT * FROM plans WHERE id=%s", (plan_id,))
    return _row_to_plan(r) if r else None


def list_plans(quote_id: Optional[str] = None, include_stale: bool = True) -> list[dict]:
    """Plan dicts (+ 'stale', 'created_at')."""
    sql, params = "SELECT * FROM plans", []
    conds = []
    if quote_id:
        conds.append("quote_id=%s")
        params.append(quote_id)
    if not include_stale:
        conds.append("stale=0")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY created_at"
    return [_row_to_plan(r) for r in query(sql, params)]


def mark_plans_stale(provider: str) -> int:
    """Mark every plan built on any of this provider's quotes stale. Call after inserting the
    new quote version and BEFORE upserting the replanned plan. Returns count."""
    qids = [q["id"] for q in query("SELECT id FROM quotes WHERE provider=%s", (provider,))]
    if not qids:
        return 0
    ph = ",".join(["%s"] * len(qids))
    return execute(f"UPDATE plans SET stale=1 WHERE quote_id IN ({ph})", qids)


# --------------------------------------------------------------------------- wishes
def insert_wish(text: str, source_id: str, *, confirmed_by: Optional[str] = None,
                confirmed_at: Optional[str] = None, wish_id: Optional[str] = None) -> str:
    wish_id = wish_id or new_id("W")
    execute("INSERT INTO wishes (id, text, source_id, confirmed_by, confirmed_at, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (wish_id, text, source_id, confirmed_by, confirmed_at or (now() if confirmed_by else None), now()))
    return wish_id


def confirm_wish(wish_id: str, confirmed_by: str) -> int:
    return execute("UPDATE wishes SET confirmed_by=%s, confirmed_at=%s WHERE id=%s", (confirmed_by, now(), wish_id))


def list_wishes() -> list[dict]:
    return query("SELECT * FROM wishes ORDER BY id")


# --------------------------------------------------------------------------- SIE trace
def log_sie_call(trace: dict, output_json: Any) -> str:
    """trace = contracts.SIETrace {recipe, model, latency_ms, input_chars}. output may be obj or JSON str."""
    cid = new_id("sie")
    out = output_json if isinstance(output_json, str) else dumps(output_json)
    execute("INSERT INTO sie_calls (id, ts, recipe, model, latency_ms, input_chars, output_json) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (cid, now(), trace.get("recipe"), trace.get("model"), trace.get("latency_ms"),
             trace.get("input_chars"), out))
    return cid


def list_sie_calls(limit: int = 200) -> list[dict]:
    """Newest first; 'output' holds the decoded output_json."""
    rows = query("SELECT * FROM sie_calls ORDER BY ts DESC LIMIT %s", (int(limit),))
    for r in rows:
        r["output"] = loads(r.get("output_json"), r.get("output_json"))
    return rows


# --------------------------------------------------------------------------- audit
def audit(actor: str, action: str, detail: Any = None) -> str:
    aid = new_id("au")
    execute("INSERT INTO audit_log (id, ts, actor, action, detail_json) VALUES (%s,%s,%s,%s,%s)",
            (aid, now(), actor, action, dumps(detail if detail is not None else {})))
    return aid


def list_audit(limit: int = 500) -> list[dict]:
    """Newest first; 'detail' holds the decoded detail_json."""
    rows = query("SELECT * FROM audit_log ORDER BY ts DESC LIMIT %s", (int(limit),))
    for r in rows:
        r["detail"] = loads(r.get("detail_json"), {})
    return rows


# --------------------------------------------------------------------------- FTC reference
def insert_ftc_ref(text: str, url: str, ref_id: Optional[str] = None) -> str:
    ref_id = ref_id or new_id("ftc")
    execute("INSERT INTO ftc_reference (id, text, url) VALUES (%s,%s,%s)", (ref_id, text, url))
    return ref_id


def list_ftc_refs() -> list[dict]:
    return query("SELECT id, text, url FROM ftc_reference ORDER BY id")


# TODO(vectors): search_ftc(query_vec, k) / search_excerpts(query_vec, k) using
#   ORDER BY text_vec <*> %s :> VECTOR(dim, F32) DESC  once LW_VECTOR_DIM + embeddings are wired.


# --------------------------------------------------------------------------- approvals / outbox reads (UI)
def list_approvals(status: Optional[str] = None) -> list[dict]:
    if status:
        rows = query("SELECT * FROM approvals WHERE status=%s ORDER BY created_at", (status,))
    else:
        rows = query("SELECT * FROM approvals ORDER BY created_at")
    for r in rows:
        r["extra"] = loads(r.get("extra_json"), {})
    return rows


def list_outbox() -> list[dict]:
    return query("SELECT * FROM outbox ORDER BY created_at")


if __name__ == "__main__":
    init_schema()
    print("backend:", backend(), "| SELECT 1 ->", query("SELECT 1 AS ok"))
