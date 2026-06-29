"""Time-series trends — bucket metrics by day / week / month / year.

Pure data builder consumed by the Flask web UI ``/trends`` route.  Mirrors the
aggregate data-path (``fetch_matching_sessions`` + ``fetch_aggregate_messages``
+ ``fetch_aggregate_ttft``) so it stays consistent with ``/aggregate``'s
numbers, then groups by a calendar period on each session's ``time_created``.

Each bucket carries the aggregate metrics for that period AND a ``by_model``
map keyed by ``provider/model`` identity, so the UI can render per-model
multi-series charts alongside the totals.

Locked time-series dict schema
------------------------------
``build_time_series`` returns::

    {
      "period": "day" | "week" | "month" | "year",
      "final_only": <bool>,
      "session_count": <int>,      # total across all buckets
      "message_count": <int>,      # total across all buckets
      "models": [<str>, ...],      # sorted distinct identities
      "buckets": [
        {
          "label": <str>,                 # calendar label, lexicographically sortable
          "session_count": <int>,
          "message_count": <int>,
          "tps_p50":   <float|null>,
          "tps_p95":   <float|null>,
          "ttft_p50":  <float|null>,       # ms
          "ttft_p95":  <float|null>,
          "tokens_input":     <int>,
          "tokens_output":    <int>,
          "tokens_reasoning": <int>,
          "tokens_total":     <int>,
          "cost":         <float>,
          "by_model": {
            "<provider/model>": { SAME metric keys (minus label) }, ...
          }
        }, ...
      ]
    }

Buckets are sorted ascending chronologically (``label`` is fixed-width so the
sort is lexicographic).  ``tps``/``ttft`` exclude low-confidence messages and
honour ``final_only`` the same way ``build_aggregate_data`` does.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .db import (
    fetch_matching_sessions,
    fetch_aggregate_messages,
    fetch_aggregate_ttft,
)
from .formatting import aggregate


PERIODS = ("day", "week", "month", "year")

# strftime formats producing fixed-width, lexicographically-sortable labels.
PERIOD_FORMATS = {
    "day": "%Y-%m-%d",
    # %G = ISO year (matches %V), %V = ISO week (01-53). Together they cross
    # year boundaries correctly (a Jan 1st session may belong to week 52 of
    # the previous ISO year).
    "week": "%G-W%V",
    "month": "%Y-%m",
    "year": "%Y",
}


# ── helpers ────────────────────────────────────────────────────────────────────

def _bucket_label(ts_ms: int | None, period: str) -> str | None:
    """Map a millisecond epoch timestamp to a period bucket label (UTC)."""
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
        PERIOD_FORMATS[period]
    )


def _bucket_metrics(sessions, messages, ttfts) -> dict:
    """Compute the locked per-bucket metric dict from raw row lists.

    ``sessions`` → token/cost totals + session count.
    ``messages`` → TPS aggregation (low-confidence + final_only already applied
    by the caller) + message count.
    ``ttfts``    → TTFT aggregation (list of {ttft_ms} dicts).
    """
    tps_values = [
        m["tps"] for m in messages
        if m["tps"] is not None and not m["low_confidence"]
    ]
    ttft_values = [t["ttft_ms"] for t in ttfts]

    tps_stats = aggregate(tps_values)
    ttft_stats = aggregate(ttft_values)

    tokens_input = sum(s["tokens_input"] for s in sessions)
    tokens_output = sum(s["tokens_output"] for s in sessions)
    tokens_reasoning = sum(s["tokens_reasoning"] for s in sessions)

    return {
        "session_count": len(sessions),
        "message_count": len(messages),
        "tps_p50": round(tps_stats["median"], 1) if tps_stats["median"] is not None else None,
        "tps_p95": round(tps_stats["p95"], 1) if tps_stats["p95"] is not None else None,
        "ttft_p50": round(ttft_stats["median"]) if ttft_stats["median"] is not None else None,
        "ttft_p95": round(ttft_stats["p95"]) if ttft_stats["p95"] is not None else None,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "tokens_reasoning": tokens_reasoning,
        "tokens_total": tokens_input + tokens_output + tokens_reasoning,
        "cost": round(sum(s["cost"] for s in sessions), 4),
    }


# ── builder (pure) ─────────────────────────────────────────────────────────────

def build_time_series(
    conn: sqlite3.Connection,
    where: str,
    params: list,
    period: str,
    final_only: bool,
) -> dict:
    """Bucket session/message/TTFT metrics by a calendar period.

    ``where``/``params`` come from ``build_session_filter`` (shared with
    discovery/aggregate).  Returns the locked time-series dict (see module
    docstring).  Raises ``ValueError`` for an unknown ``period``.
    """
    if period not in PERIODS:
        raise ValueError(
            f"period must be one of {PERIODS}, got {period!r}"
        )

    sessions = fetch_matching_sessions(conn, where, params)
    if not sessions:
        return {
            "period": period,
            "final_only": final_only,
            "session_count": 0,
            "message_count": 0,
            "models": [],
            "buckets": [],
        }

    session_ids = [s["id"] for s in sessions]
    messages = fetch_aggregate_messages(conn, session_ids)
    ttft_rows = fetch_aggregate_ttft(conn, session_ids, final_only=final_only)

    # Mirror build_aggregate_data: --final-only filters TPS message-level stats
    # (TTFT is already SQL-filtered in fetch_aggregate_ttft).
    msgs_for_stats = (
        [m for m in messages if m["finish"] == "stop"]
        if final_only else messages
    )

    # Index sessions/messages/TTFTs by bucket label.  Sessions and messages are
    # bucketed by the owning session's time_created so a session's metrics all
    # land in one bucket (matches how /aggregate scopes a value to a session).
    sess_lookup = {s["id"]: s for s in sessions}
    sess_by_bucket: dict[str, list] = {}
    for s in sessions:
        label = _bucket_label(s["time_created"], period)
        if label is not None:
            sess_by_bucket.setdefault(label, []).append(s)

    msg_by_bucket: dict[str, list] = {}
    for m in msgs_for_stats:
        s = sess_lookup.get(m["session_id"])
        if s is None:
            continue
        label = _bucket_label(s["time_created"], period)
        if label is not None:
            msg_by_bucket.setdefault(label, []).append(m)

    ttft_by_bucket: dict[str, list] = {}
    for t in ttft_rows:
        s = sess_lookup.get(t["session_id"])
        if s is None:
            continue
        label = _bucket_label(s["time_created"], period)
        if label is not None:
            ttft_by_bucket.setdefault(label, []).append(t)

    # Distinct model identities across all buckets, sorted for stable colors.
    models = sorted({s["model_identity"] for s in sessions})

    # Deterministic ascending bucket order (labels are fixed-width sortable).
    all_labels = sorted(set(sess_by_bucket) | set(msg_by_bucket) | set(ttft_by_bucket))

    buckets = []
    for label in all_labels:
        sess_list = sess_by_bucket.get(label, [])
        msg_list = msg_by_bucket.get(label, [])
        ttft_list = ttft_by_bucket.get(label, [])

        # Per-model grouping within this bucket.
        sess_by_model: dict[str, list] = {}
        for s in sess_list:
            sess_by_model.setdefault(s["model_identity"], []).append(s)
        msg_by_model: dict[str, list] = {}
        for m in msg_list:
            msg_by_model.setdefault(
                f"{m['provider_id']}/{m['model_id']}", []
            ).append(m)
        ttft_by_model: dict[str, list] = {}
        for t in ttft_list:
            mid = sess_lookup.get(t["session_id"], {}).get("model_identity")
            if mid:
                ttft_by_model.setdefault(mid, []).append(t)

        by_model = {}
        for mid in set(sess_by_model) | set(msg_by_model) | set(ttft_by_model):
            by_model[mid] = _bucket_metrics(
                sess_by_model.get(mid, []),
                msg_by_model.get(mid, []),
                ttft_by_model.get(mid, []),
            )

        bucket = _bucket_metrics(sess_list, msg_list, ttft_list)
        bucket["label"] = label
        bucket["by_model"] = by_model
        buckets.append(bucket)

    return {
        "period": period,
        "final_only": final_only,
        "session_count": len(sessions),
        "message_count": len(msgs_for_stats),
        "models": models,
        "buckets": buckets,
    }
