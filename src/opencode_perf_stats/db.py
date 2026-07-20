"""Database connection and query functions for OpenCode's SQLite database."""

import json
import os
import sqlite3
import sys

from .formatting import fmt_ts


# ── connection ────────────────────────────────────────────────────────────────

def resolve_db_path() -> str:
    """Resolve the opencode database path, honoring XDG_DATA_HOME."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return os.path.join(xdg, "opencode", "opencode.db")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "opencode.db")


def connect(db_path: str) -> sqlite3.Connection:
    """Open a read-only connection with a busy timeout.

    Two layers of busy-timeout defense:
      - `timeout=10` on connect()  (maps to busy_timeout=10000ms)
      - explicit `PRAGMA busy_timeout` for clarity/documentation
    """
    if not os.path.exists(db_path):
        sys.stderr.write(f"error: database not found at {db_path}\n")
        sys.exit(1)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    # Belt-and-braces: explicit pragma documents intent alongside the connect arg.
    conn.execute("PRAGMA busy_timeout = 3000")
    return conn


# ── filter helpers ────────────────────────────────────────────────────────────

def build_session_filter(args) -> tuple[str, list]:
    """Build a WHERE clause fragment + params for --days/--model on the session table.

    Model filter matches against the ``provider/model`` identity format
    (e.g. ``xiaomi/mimo-v2.5-pro``).  Falls back to matching just the model ID
    when the filter string contains no ``/``.
    """
    clauses: list[str] = []
    params: list = []
    if args.days is not None:
        clauses.append("time_created > strftime('%s','now',?) * 1000")
        params.append(f"-{int(args.days)} days")
    if args.model is not None:
        if "/" in args.model:
            # provider/model format: match providerID + model.id together
            provider, model_part = args.model.split("/", 1)
            clauses.append(
                "LOWER(json_extract(model, '$.providerID') || '/' || json_extract(model, '$.id')) LIKE LOWER(?)"
            )
            params.append(f"%{provider}/{model_part}%")
        else:
            # Backward-compat: match just model ID substring
            clauses.append("LOWER(json_extract(model, '$.id')) LIKE LOWER(?)")
            params.append(f"%{args.model}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# ── single-session data fetching ──────────────────────────────────────────────

def get_session_id(conn: sqlite3.Connection, explicit: str | None) -> str:
    """Return the session ID to report on: explicit arg or most recently updated."""
    if explicit:
        row = conn.execute(
            "SELECT id FROM session WHERE id = ?", (explicit,)
        ).fetchone()
        if not row:
            sys.stderr.write(f"error: session '{explicit}' not found\n")
            sys.exit(1)
        return explicit

    row = conn.execute(
        "SELECT id FROM session ORDER BY time_updated DESC LIMIT 1"
    ).fetchone()
    if not row:
        sys.stderr.write("error: no sessions found in database\n")
        sys.exit(1)
    return row["id"]


def fetch_session(conn: sqlite3.Connection, session_id: str) -> dict:
    """Fetch session-level summary data."""
    row = conn.execute(
        """SELECT id, title, agent, model, cost,
                  tokens_input, tokens_output, tokens_reasoning,
                  tokens_cache_read, tokens_cache_write,
                  time_created, time_updated, time_compacting, metadata
           FROM session WHERE id = ?""",
        (session_id,),
    ).fetchone()
    if not row:
        sys.stderr.write(f"error: session '{session_id}' not found\n")
        sys.exit(1)

    model_raw = json.loads(row["model"]) if row["model"] else {}
    metadata = json.loads(row["metadata"]) if row["metadata"] else {}

    return {
        "id": row["id"],
        "title": row["title"] or "(untitled)",
        "agent": row["agent"] or "(unknown)",
        "model": model_raw.get("id", "(unknown)"),
        "provider": model_raw.get("providerID", "(unknown)"),
        "variant": model_raw.get("variant"),
        "cost": row["cost"] or 0.0,
        "tokens_input": row["tokens_input"] or 0,
        "tokens_output": row["tokens_output"] or 0,
        "tokens_reasoning": row["tokens_reasoning"] or 0,
        "tokens_cache_read": row["tokens_cache_read"] or 0,
        "tokens_cache_write": row["tokens_cache_write"] or 0,
        "time_created": row["time_created"],
        "time_updated": row["time_updated"],
        "time_compacting": row["time_compacting"],
        "metadata": metadata,
    }


def fetch_assistant_messages(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    """Fetch all assistant messages with token/timing data for one session."""
    rows = conn.execute(
        """SELECT id,
                  json_extract(data, '$.time.created')    as created,
                  json_extract(data, '$.time.completed')  as completed,
                  json_extract(data, '$.tokens.output')   as output_tokens,
                  json_extract(data, '$.tokens.input')    as input_tokens,
                  json_extract(data, '$.tokens.reasoning') as reasoning_tokens,
                  json_extract(data, '$.tokens.cache.read')  as cache_read,
                  json_extract(data, '$.tokens.cache.write') as cache_write,
                  json_extract(data, '$.cost')            as cost,
                  json_extract(data, '$.finish')          as finish,
                  json_extract(data, '$.modelID')         as model_id,
                  json_extract(data, '$.providerID')      as provider_id
           FROM message
           WHERE session_id = ?
             AND json_extract(data, '$.role') = 'assistant'
           ORDER BY time_created""",
        (session_id,),
    ).fetchall()

    messages = []
    for r in rows:
        created = r["created"]
        completed = r["completed"]
        output_tokens = r["output_tokens"] or 0
        has_timing = created is not None and completed is not None and output_tokens > 0
        duration_ms = (completed - created) if has_timing else None
        tps = (output_tokens / (duration_ms / 1000)) if (has_timing and duration_ms > 0) else None

        # Low-confidence: noisy TPS from short durations OR tiny token counts.
        low_conf = has_timing and (output_tokens < 20 or (duration_ms is not None and duration_ms < 1000))
        low_conf_reason = None
        if low_conf:
            if duration_ms is not None and duration_ms < 1000:
                low_conf_reason = "short duration (<1s)"
            elif output_tokens < 20:
                low_conf_reason = "low token count (<20)"

        messages.append({
            "id": r["id"],
            "created": created,
            "completed": completed,
            "output_tokens": output_tokens,
            "input_tokens": r["input_tokens"] or 0,
            "reasoning_tokens": r["reasoning_tokens"] or 0,
            "cache_read": r["cache_read"] or 0,
            "cache_write": r["cache_write"] or 0,
            "cost": r["cost"] or 0.0,
            "finish": r["finish"],
            "model_id": r["model_id"],
            "provider_id": r["provider_id"],
            "has_timing": has_timing,
            "duration_ms": duration_ms,
            "tps": tps,
            "low_confidence": low_conf,
            "low_confidence_reason": low_conf_reason,
        })
    return messages


def fetch_user_messages(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    """Fetch all user messages for a session (the prompts).

    User messages carry no token/timing/finish data — only an id,
    ``$.time.created``, and session context metadata (agent, model, variant).
    Content is stored in the ``part`` table and is accessible via
    ``fetch_message_parts`` (same as assistant messages).
    """
    rows = conn.execute(
        """SELECT id,
                  json_extract(data, '$.time.created') as created,
                  json_extract(data, '$.agent')        as agent,
                  json_extract(data, '$.model')        as model_json,
                  json_extract(data, '$.variant')      as variant
           FROM message
           WHERE session_id = ?
             AND json_extract(data, '$.role') = 'user'
           ORDER BY time_created""",
        (session_id,),
    ).fetchall()
    result = []
    for r in rows:
        model_raw = json.loads(r["model_json"]) if r["model_json"] else {}
        result.append({
            "id": r["id"],
            "created": r["created"],
            "agent": r["agent"],
            "model_id": model_raw.get("id"),
            "provider_id": model_raw.get("providerID"),
            "variant": r["variant"],
        })
    return result


def fetch_ttft(conn: sqlite3.Connection, session_id: str) -> dict[str, dict]:
    """Return {message_id: {ttft_ms, part_type}} for first part with time.start.

    Considers ALL part types (text, reasoning, etc.) so tool-call-only messages
    (which have no text part) still get a TTFT via their reasoning part.
    Some text parts lack a time object entirely — the IS NOT NULL filter skips them.
    """
    rows = conn.execute(
        """SELECT m.id as message_id,
                  json_extract(m.data, '$.time.created') as msg_created,
                  MIN(json_extract(p.data, '$.time.start')) as first_token_time
           FROM message m
           JOIN part p ON p.message_id = m.id
           WHERE m.session_id = ?
             AND json_extract(m.data, '$.role') = 'assistant'
             AND json_extract(p.data, '$.time.start') IS NOT NULL
           GROUP BY m.id""",
        (session_id,),
    ).fetchall()

    # Second pass: determine the part_type of the earliest timed part.
    result = {}
    for r in rows:
        msg_id = r["message_id"]
        msg_created = r["msg_created"]
        first_token = r["first_token_time"]
        if msg_created is None or first_token is None:
            continue
        # Look up which part type carried the min time.start
        type_row = conn.execute(
            """SELECT json_extract(p.data, '$.type') as ptype
               FROM part p
               WHERE p.message_id = ?
                 AND json_extract(p.data, '$.time.start') = ?
               LIMIT 1""",
            (msg_id, first_token),
        ).fetchone()
        part_type = type_row["ptype"] if type_row else "unknown"
        result[msg_id] = {"ttft_ms": first_token - msg_created, "part_type": part_type}
    return result


# ── multi-session data fetching ──────────────────────────────────────────────

def fetch_matching_sessions(conn: sqlite3.Connection, where: str, params: list) -> list[dict]:
    """Fetch summary rows for all sessions matching the filter."""
    # When no WHERE clause is present, start the predicate with WHERE instead of AND.
    token_clause = "WHERE tokens_input > 0" if not where else where + " AND tokens_input > 0"
    rows = conn.execute(
        f"""SELECT id, title, agent, model, cost,
                   tokens_input, tokens_output, tokens_reasoning,
                   tokens_cache_read, tokens_cache_write,
                   time_created, time_updated
            FROM session
              {token_clause}
            ORDER BY time_updated DESC""",
        params,
    ).fetchall()
    out = []
    for r in rows:
        model_raw = json.loads(r["model"]) if r["model"] else {}
        provider = model_raw.get("providerID", "(unknown)")
        model_id = model_raw.get("id", "(unknown)")
        out.append({
            "id": r["id"],
            "title": r["title"] or "(untitled)",
            "agent": r["agent"] or "(unknown)",
            "model": model_id,
            "provider": provider,
            "model_identity": f"{provider}/{model_id}",
            "cost": r["cost"] or 0.0,
            "tokens_input": r["tokens_input"] or 0,
            "tokens_output": r["tokens_output"] or 0,
            "tokens_reasoning": r["tokens_reasoning"] or 0,
            "tokens_cache_read": r["tokens_cache_read"] or 0,
            "tokens_cache_write": r["tokens_cache_write"] or 0,
            "time_created": r["time_created"],
            "time_updated": r["time_updated"],
        })
    return out


def fetch_aggregate_messages(conn: sqlite3.Connection, session_ids: list[str]) -> list[dict]:
    """Fetch assistant messages with timing across many sessions (two-pass: avoid 3-table join)."""
    if not session_ids:
        return []
    # Bind list via temp table to avoid arg limit.
    conn.execute("CREATE TEMP TABLE _agg_sessions(id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO _agg_sessions(id) VALUES (?)", [(s,) for s in session_ids])

    rows = conn.execute(
        """SELECT m.id,
                  m.session_id,
                  json_extract(m.data, '$.time.created')    as created,
                  json_extract(m.data, '$.time.completed')  as completed,
                  json_extract(m.data, '$.tokens.output')   as output_tokens,
                  json_extract(m.data, '$.cost')            as cost,
                  json_extract(m.data, '$.finish')          as finish,
                  json_extract(m.data, '$.modelID')         as model_id,
                  json_extract(m.data, '$.providerID')      as provider_id
           FROM message m
           JOIN _agg_sessions s ON s.id = m.session_id
           WHERE json_extract(m.data, '$.role') = 'assistant'
             AND json_extract(m.data, '$.tokens.output') > 0
             AND json_extract(m.data, '$.time.completed') IS NOT NULL
           ORDER BY m.time_created"""
    ).fetchall()

    messages = []
    for r in rows:
        created = r["created"]
        completed = r["completed"]
        output_tokens = r["output_tokens"]
        duration_ms = completed - created
        tps = (output_tokens / (duration_ms / 1000)) if duration_ms > 0 else None
        low_conf = output_tokens < 20 or duration_ms < 1000
        messages.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "output_tokens": output_tokens,
            "cost": r["cost"] or 0.0,
            "finish": r["finish"],
            "model_id": r["model_id"],
            "provider_id": r["provider_id"],
            "duration_ms": duration_ms,
            "tps": tps,
            "low_confidence": low_conf,
        })

    conn.execute("DROP TABLE _agg_sessions")
    return messages


def fetch_aggregate_ttft(conn: sqlite3.Connection, session_ids: list[str], final_only: bool) -> list[dict]:
    """Fetch per-message TTFT (earliest-any part) across many sessions."""
    if not session_ids:
        return []
    conn.execute("CREATE TEMP TABLE _agg_sessions(id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO _agg_sessions(id) VALUES (?)", [(s,) for s in session_ids])

    finish_filter = ""
    if final_only:
        finish_filter = "AND json_extract(m.data, '$.finish') = 'stop'"

    rows = conn.execute(
        f"""SELECT m.id as message_id,
                   m.session_id,
                   json_extract(m.data, '$.time.created') as msg_created,
                   MIN(json_extract(p.data, '$.time.start')) as first_token_time
            FROM message m
            JOIN part p ON p.message_id = m.id
            JOIN _agg_sessions s ON s.id = m.session_id
            WHERE json_extract(m.data, '$.role') = 'assistant'
              AND json_extract(p.data, '$.time.start') IS NOT NULL
              {finish_filter}
            GROUP BY m.id, m.session_id"""
    ).fetchall()

    out = []
    for r in rows:
        msg_created = r["msg_created"]
        first_token = r["first_token_time"]
        if msg_created is not None and first_token is not None:
            out.append({
                "message_id": r["message_id"],
                "session_id": r["session_id"],
                "ttft_ms": first_token - msg_created,
            })

    conn.execute("DROP TABLE _agg_sessions")
    return out


# ── comparison data fetching ──────────────────────────────────────────────────

def fetch_sessions_by_ids(conn: sqlite3.Connection, session_ids: list[str]) -> list[dict]:
    """Fetch summary data for multiple specific sessions (for comparison mode)."""
    if not session_ids:
        return []
    results = []
    for sid in session_ids:
        session = fetch_session(conn, sid)
        results.append(session)
    return results


# ── discovery (shared by CLI --list and web /) ────────────────────────────────

def fetch_discovery_sessions(
    conn: sqlite3.Connection, where: str, params: list, limit: int = 20
) -> list[dict]:
    """Return recent sessions for discovery (shared by CLI --list and web /).

    Same SELECT currently used inside ``cmd_list``; returns the list of dicts
    that the JSON branch of ``cmd_list`` already constructs internally.
    """
    rows = conn.execute(
        f"""SELECT id, title, agent, model, cost,
                  tokens_output, tokens_input,
                  time_created, time_updated
           FROM session{where}
           ORDER BY time_updated DESC LIMIT ?""",
        (*params, limit),
    ).fetchall()

    out = []
    for r in rows:
        model_raw = json.loads(r["model"]) if r["model"] else {}
        provider = model_raw.get("providerID", "(unknown)")
        model_id = model_raw.get("id", "(unknown)")
        out.append({
            "id": r["id"],
            "title": r["title"] or "(untitled)",
            "agent": r["agent"] or "(unknown)",
            "model": model_id,
            "provider": provider,
            "model_identity": f"{provider}/{model_id}",
            "tokens_output": r["tokens_output"] or 0,
            "tokens_input": r["tokens_input"] or 0,
            "cost": r["cost"] or 0.0,
            "time_created": r["time_created"],
            "time_updated": r["time_updated"],
            # pre-formatted for display convenience
            "created": fmt_ts(r["time_created"]),
            "updated": fmt_ts(r["time_updated"]),
        })
    return out


def fetch_message_parts(conn: sqlite3.Connection, message_id: str) -> list[dict]:
    """Fetch all content-bearing parts for a given assistant message.

    Returns a list of dicts with ``type`` and content fields.  Only
    content-bearing types (text, reasoning, tool, etc.) are included;
    timing-only parts are skipped.  Unknown types carry a raw ``data``
    preview so the frontend can fall back gracefully.

    The caller MUST validate that ``message_id`` belongs to the expected
    session before calling this function.
    """
    rows = conn.execute(
        """SELECT json_extract(p.data, '$.type') as ptype, p.data
           FROM part p
           WHERE p.message_id = ?
           ORDER BY p.time_created""",
        (message_id,),
    ).fetchall()

    parts = []
    for r in rows:
        ptype = r["ptype"] or "unknown"
        raw = json.loads(r["data"]) if r["data"] else {}

        try:
            if ptype == "text":
                text = raw.get("text", "")
                parts.append({"type": "text", "text": text})
            elif ptype == "reasoning":
                text = raw.get("text", "") or raw.get("reasoning", "")
                parts.append({"type": "reasoning", "text": text})
            elif ptype == "tool-call":
                parts.append({
                    "type": "tool-call",
                    "name": raw.get("name", raw.get("tool", "(unknown)")),
                    "input": raw.get("input", raw.get("arguments", "")),
                })
            elif ptype == "tool-result":
                parts.append({
                    "type": "tool-result",
                    "name": raw.get("name", raw.get("tool", "(unknown)")),
                    "output": raw.get("output", raw.get("result", "")),
                })
            else:
                # Unknown type — include raw data preview for the frontend.
                parts.append({"type": ptype, "raw": json.dumps(raw, default=str)[:5000]})
        except Exception:
            # Malformed JSON — still return something useful.
            parts.append({"type": ptype, "raw": r["data"][:5000] if r["data"] else ""})

    return parts


def fetch_distinct_models(conn: sqlite3.Connection) -> list[dict]:
    """Return distinct ``provider/model`` identities with session counts.

    Each entry: ``{"identity": "provider/model", "provider": ..., "model": ..., "count": int}``.
    """
    rows = conn.execute(
        """SELECT json_extract(model, '$.providerID') as provider,
                  json_extract(model, '$.id') as model_id,
                  COUNT(*) as cnt
           FROM session
           WHERE model IS NOT NULL AND tokens_input > 0
           GROUP BY provider, model_id
           ORDER BY cnt DESC"""
    ).fetchall()

    out = []
    for r in rows:
        provider = r["provider"] or "(unknown)"
        model_id = r["model_id"] or "(unknown)"
        out.append({
            "identity": f"{provider}/{model_id}",
            "provider": provider,
            "model": model_id,
            "count": r["cnt"],
        })
    return out
