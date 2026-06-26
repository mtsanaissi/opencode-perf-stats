"""Comparison mode — compare sessions, models, or date ranges.

Pure data builders that both the CLI (``run_compare``) and the Flask web UI
(``compare`` route) consume. The CLI is a thin wrapper that dispatches these
builders to JSON / Markdown / HTML output.

Locked comparison dict schema
-----------------------------
Each builder returns::

    {
      "type": "sessions" | "models" | "days",
      "count": <int>,
      "items": [
        {
          "label": <str>,            # comparison column label
          # type-specific identity keys:
          #   sessions: "id", "model"
          #   models:    "model"
          #   days:      "days"
          # plus, for sessions/models: "session_count" (models/days only),
          # and for sessions a top-level "title" is folded into "label".
          "metrics": {
            "tps_mean":     <float|null>,
            "tps_median":   <float|null>,
            "ttft_mean":    <float|null>,   # ms
            "ttft_median":  <float|null>,
            "tokens_input":     <int>,
            "tokens_output":    <int>,
            "tokens_reasoning": <int>,
            "tokens_total":     <int>,
            "cost":         <float>,
            "duration_seconds": <float|null>,   # sessions only
            "message_count":    <int>,
            "finish_stop":      <int>,   # sessions only (0 elsewhere)
            "finish_tool_calls": <int>,  # sessions only (0 elsewhere)
          }
        }, ...
      ]
    }

``metrics`` uses the same set of keys across all three types where applicable;
unknown/inapplicable keys are ``None`` or ``0``.

Usage:
    opencode-perf-stats compare sessions ses_a ses_b [ses_c] [ses_d]
    opencode-perf-stats compare models mimo gpt-4 claude
    opencode-perf-stats compare days 7 30
"""

import json
import sqlite3
import sys

from .db import (
    connect,
    resolve_db_path,
    fetch_session,
    fetch_assistant_messages,
    fetch_ttft,
    build_session_filter,
    fetch_matching_sessions,
    fetch_aggregate_messages,
    fetch_aggregate_ttft,
)
from .reports.markdown import build_report_data, build_aggregate_data


# ── shared metrics extraction ────────────────────────────────────────────────

def _or_zero(v) -> float:
    return v if v is not None else 0.0


def _metrics_from_single(data: dict) -> dict:
    """Extract a metrics dict from a single-session ``build_report_data`` result."""
    tps = data["tps"]["aggregate"]
    ttft = data["ttft"]["aggregate"]
    t = data["tokens"]
    s = data["session"]
    m = data["messages"]
    return {
        "tps_mean": tps["mean"],
        "tps_median": tps["median"],
        "ttft_mean": ttft["mean"],
        "ttft_median": ttft["median"],
        "tokens_input": t["input"],
        "tokens_output": t["output"],
        "tokens_reasoning": t["reasoning"],
        "tokens_total": t["input"] + t["output"] + t["reasoning"],
        "cost": t["cost"],
        "duration_seconds": s["duration_seconds"],
        "message_count": m["total_assistant"],
        "finish_stop": m["finish_stop"],
        "finish_tool_calls": m["finish_tool_calls"],
    }


def _metrics_from_aggregate(data: dict) -> dict:
    """Extract a metrics dict from an aggregate ``build_aggregate_data`` result.

    No per-session duration or finish breakdown at aggregate level.
    """
    tps = data["tps"]["aggregate"]
    ttft = data["ttft"]["aggregate"]
    t = data["tokens"]
    ov = data["overview"]
    return {
        "tps_mean": tps["mean"],
        "tps_median": tps["median"],
        "ttft_mean": ttft["mean"],
        "ttft_median": ttft["median"],
        "tokens_input": t["input"],
        "tokens_output": t["output"],
        "tokens_reasoning": 0,  # not surfaced in aggregate tokens dict
        "tokens_total": t["input"] + t["output"],
        "cost": t["cost"],
        "duration_seconds": None,
        "message_count": ov["message_count"],
        "finish_stop": 0,
        "finish_tool_calls": 0,
    }


# ── comparison data builders (pure) ──────────────────────────────────────────

def build_sessions_comparison(conn: sqlite3.Connection, session_ids: list[str]) -> dict:
    """Build a side-by-side sessions comparison dict.

    Accepts 2–4 session IDs. Raises ValueError if the count is out of range.
    Returns the locked dict schema (see module docstring).
    """
    if len(session_ids) < 2:
        raise ValueError("need at least 2 sessions to compare")
    if len(session_ids) > 4:
        raise ValueError("can compare at most 4 sessions at once")

    items = []
    for sid in session_ids:
        # Validate existence by fetching; fetch_session calls sys.exit on missing.
        # The web layer catches SystemExit; here we let it propagate so callers
        # that want to map to 404 can intercept.
        session = fetch_session(conn, sid)
        messages = fetch_assistant_messages(conn, sid)
        ttft_map = fetch_ttft(conn, sid)
        data = build_report_data(session, messages, ttft_map, final_only=False)

        items.append({
            "label": session["title"],
            "id": sid,
            "model": f"{session['provider']}/{session['model']}",
            "metrics": _metrics_from_single(data),
        })

    return {"type": "sessions", "count": len(items), "items": items}


def build_models_comparison(conn: sqlite3.Connection, model_names: list[str]) -> dict:
    """Build a side-by-side models comparison dict.

    Accepts ≥2 model name substrings. Returns the locked dict schema.
    Items with no matching sessions get an empty-metrics entry with session_count=0.
    """
    if len(model_names) < 2:
        raise ValueError("need at least 2 models to compare")

    items = []
    for model_name in model_names:
        # Build filter with explicit model param (no FakeArgs hack).
        class _Params:
            pass
        p = _Params()
        p.days = None
        p.model = model_name
        where, params = build_session_filter(p)

        sessions = fetch_matching_sessions(conn, where, params)
        if not sessions:
            items.append({
                "label": model_name,
                "model": model_name,
                "session_count": 0,
                "metrics": _empty_metrics(),
            })
            continue

        session_ids = [s["id"] for s in sessions]
        messages = fetch_aggregate_messages(conn, session_ids)
        ttft_rows = fetch_aggregate_ttft(conn, session_ids, final_only=False)
        data = build_aggregate_data(sessions, messages, ttft_rows, final_only=False)

        items.append({
            "label": model_name,
            "model": model_name,
            "session_count": len(sessions),
            "metrics": _metrics_from_aggregate(data),
        })

    return {"type": "models", "count": len(items), "items": items}


def build_days_comparison(conn: sqlite3.Connection, day_ints: list[int]) -> dict:
    """Build a side-by-side date-range comparison dict.

    Accepts ≥2 ``--days``-style integers (days back from now). Returns the locked schema.
    """
    if len(day_ints) < 2:
        raise ValueError("need at least 2 date ranges to compare")

    items = []
    for days in day_ints:
        where = " WHERE time_created > strftime('%s','now',?) * 1000 AND tokens_input > 0"
        params = [f"-{int(days)} days"]

        sessions = fetch_matching_sessions(conn, where, params)
        if not sessions:
            items.append({
                "label": f"Last {days} days",
                "days": days,
                "session_count": 0,
                "metrics": _empty_metrics(),
            })
            continue

        session_ids = [s["id"] for s in sessions]
        messages = fetch_aggregate_messages(conn, session_ids)
        ttft_rows = fetch_aggregate_ttft(conn, session_ids, final_only=False)
        data = build_aggregate_data(sessions, messages, ttft_rows, final_only=False)

        items.append({
            "label": f"Last {days} days",
            "days": days,
            "session_count": len(sessions),
            "metrics": _metrics_from_aggregate(data),
        })

    return {"type": "days", "count": len(items), "items": items}


def _empty_metrics() -> dict:
    """Metrics dict for an item with no matching sessions."""
    return {
        "tps_mean": None, "tps_median": None,
        "ttft_mean": None, "ttft_median": None,
        "tokens_input": 0, "tokens_output": 0, "tokens_reasoning": 0,
        "tokens_total": 0, "cost": 0.0, "duration_seconds": None,
        "message_count": 0, "finish_stop": 0, "finish_tool_calls": 0,
    }


# ── CLI entry (thin wrapper) ─────────────────────────────────────────────────

def run_compare(args) -> None:
    """Execute comparison mode based on the compare subcommand (CLI dispatch)."""
    compare_type = args.type
    values = args.values

    db_path = getattr(args, "db", None) or resolve_db_path()
    conn = connect(db_path)

    try:
        if compare_type == "sessions":
            comparison = build_sessions_comparison(conn, values)
        elif compare_type == "models":
            comparison = build_models_comparison(conn, values)
        elif compare_type == "days":
            day_ints = _parse_days(values)
            comparison = build_days_comparison(conn, day_ints)
        else:
            sys.stderr.write(f"error: unknown comparison type '{compare_type}'\n")
            sys.exit(1)
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(1)
    finally:
        conn.close()

    if getattr(args, "compare_json", False):
        print(json.dumps(comparison, indent=2, default=str))
    elif getattr(args, "compare_html", None) is not None:
        from .reports.html import render_compare_html
        html = render_compare_html(comparison)
        _write_html(html, args.compare_html, "opencode-perf-stats-compare.html")
    else:
        _print_comparison(comparison)


def _parse_days(values: list[str]) -> list[int]:
    """Parse --days-style integers from string values."""
    day_ints = []
    for d in values:
        try:
            day_ints.append(int(d))
        except ValueError:
            sys.stderr.write(f"error: '{d}' is not a valid number of days\n")
            sys.exit(1)
    return day_ints


def _write_html(html: str, path: str, default_name: str) -> None:
    """Write HTML to file or stdout."""
    if path == "-":
        print(html)
    else:
        filename = path if path != "-" else default_name
        with open(filename, "w") as f:
            f.write(html)
        sys.stderr.write(f"HTML report written to {filename}\n")


# ── Markdown output (reads from locked items[*].metrics) ─────────────────────

def _print_comparison(comparison: dict) -> None:
    """Print a side-by-side Markdown comparison from the locked dict schema."""
    ctype = comparison["type"]
    items = comparison["items"]

    if ctype == "sessions":
        _print_session_comparison(items)
    elif ctype == "models":
        _print_model_comparison(items)
    elif ctype == "days":
        _print_day_comparison(items)


def _fmt_metric(metrics: dict, key: str) -> str:
    v = metrics.get(key)
    if v is None:
        return "—"
    if key in ("tps_mean", "tps_median"):
        return f"{v:.1f}"
    if key in ("ttft_mean", "ttft_median"):
        return f"{v:.0f}ms"
    if key == "cost":
        return f"${v:.4f}"
    if key == "duration_seconds":
        if v is None:
            return "—"
        return f"{v:.0f}s"
    if key == "tokens_total":
        return f"{v:,}"
    return str(v)


def _print_session_comparison(items: list[dict]) -> None:
    print("## Session Comparison\n")
    labels = [i["label"][:25] for i in items]
    print(f"| Metric | {' | '.join(labels)} |")
    print(f"|--------|{'|'.join('---' for _ in items)}|")
    print(f"| Model | {' | '.join(i['model'] for i in items)} |")
    _print_metric_rows(items)


def _print_model_comparison(items: list[dict]) -> None:
    print("## Model Comparison\n")
    labels = [i["label"] for i in items]
    print(f"| Metric | {' | '.join(labels)} |")
    print(f"|--------|{'|'.join('---' for _ in items)}|")
    print(f"| Sessions | {' | '.join(str(i['session_count']) for i in items)} |")
    _print_metric_rows(items)


def _print_day_comparison(items: list[dict]) -> None:
    print("## Date Range Comparison\n")
    labels = [i["label"] for i in items]
    print(f"| Metric | {' | '.join(labels)} |")
    print(f"|--------|{'|'.join('---' for _ in items)}|")
    print(f"| Sessions | {' | '.join(str(i['session_count']) for i in items)} |")
    _print_metric_rows(items)


def _print_metric_rows(items: list[dict]) -> None:
    """Print TPS/TTFT/Cost/Tokens/Messages/Duration rows from metrics."""
    for key, label in [
        ("tps_mean", "TPS Mean"),
        ("ttft_mean", "TTFT Mean"),
        ("cost", "Cost"),
        ("tokens_total", "Total Tokens"),
        ("message_count", "Messages"),
        ("duration_seconds", "Duration"),
    ]:
        vals = [_fmt_metric(i["metrics"], key) for i in items]
        print(f"| {label} | {' | '.join(vals)} |")
    print()
