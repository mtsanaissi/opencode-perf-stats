"""Flask application factory and routes for the opencode-perf-stats web UI.

DB connection lifecycle uses Flask's ``g`` object + ``teardown_appcontext``:
one read-only SQLite connection per request (matches the CLI's per-invocation
model; reuses ``db.connect`` which sets ``mode=ro`` and a 3s busy timeout).

Error handling:
  - 404 for missing sessions / params referring to nonexistent resources
  - 400 for invalid params (too few/many compare items, non-integer days)
  - 500 for unexpected errors (logged to stderr)
"""

from __future__ import annotations

import os
import sys

from flask import (
    Flask, g, render_template, request, abort, redirect, url_for, jsonify,
)

from .. import __version__
from ..db import (
    connect,
    resolve_db_path,
    get_session_id,
    fetch_session,
    fetch_assistant_messages,
    fetch_ttft,
    build_session_filter,
    fetch_matching_sessions,
    fetch_aggregate_messages,
    fetch_aggregate_ttft,
    fetch_discovery_sessions,
)
from ..reports.markdown import build_report_data, build_aggregate_data
from ..compare import (
    build_sessions_comparison, build_models_comparison, build_days_comparison,
)


# ── application factory ─────────────────────────────────────────────────────

def create_app(db_path: str | None = None) -> Flask:
    """Create the Flask app configured to read from ``db_path``.

    If ``db_path`` is None, ``db.resolve_db_path()`` is used at request time.
    """
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or resolve_db_path()
    # Stable-enough secret key for signed cookies/session state (local tool).
    app.config["SECRET_KEY"] = os.environ.get(
        "OPENCODE_PERF_STATS_SECRET", os.urandom(32).hex()
    )
    app.config["VERSION"] = __version__

    # Register teardown and error handlers.
    app.teardown_appcontext(_close_db)
    app.register_error_handler(404, _handle_error)
    app.register_error_handler(400, _handle_error)
    app.register_error_handler(500, _handle_error)

    # Inject shared context (nav state, version) into every template.
    @app.context_processor
    def _inject_globals():
        return {"version": app.config["VERSION"], "db_path": app.config["DB_PATH"]}

    # Register a metric formatter for the comparison template (called as a function).
    @app.template_global("_fmt")
    def _fmt_metric(metrics, key):
        """Format a comparison metric cell (matches reports/html._fmt_cmp_metric)."""
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
            if v < 60:
                return f"{v:.0f}s"
            if v < 3600:
                return f"{int(v // 60)}m {v % 60:.0f}s"
            return f"{int(v // 3600)}h {int((v % 3600) // 60)}m"
        if key in ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_total", "message_count"):
            return f"{v:,}"
        return str(v)

    app.add_url_rule("/", "discovery", discovery, methods=["GET"])
    app.add_url_rule("/session/<session_id>", "session_report", session_report, methods=["GET"])
    app.add_url_rule("/aggregate", "aggregate", aggregate_report, methods=["GET"])
    app.add_url_rule("/compare/sessions", "compare_sessions", compare_sessions, methods=["GET"])
    app.add_url_rule("/compare/models", "compare_models", compare_models, methods=["GET"])
    app.add_url_rule("/compare/days", "compare_days", compare_days, methods=["GET"])
    app.add_url_rule("/compare", "compare_landing", compare_landing, methods=["GET"])

    return app


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_db():
    """Lazily open a per-request read-only DB connection stored on ``g``."""
    if "db" not in g:
        g.db = connect(g.get("_db_path") or current_db_path())
    return g.db


def current_db_path() -> str:
    from flask import current_app
    return current_app.config["DB_PATH"]


def _close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ── error handling ───────────────────────────────────────────────────────────

def _handle_error(err):
    code = getattr(err, "code", 500)
    message = getattr(err, "description", "An unexpected error occurred.")
    # Custom messages set via abort(..., description=...) come through.
    if code == 404 and not isinstance(err, str):
        message = getattr(err, "description", message)
    return render_template("error.html", error_code=code, error_message=message, nav=None), code


# ── arg parsing helpers ──────────────────────────────────────────────────────

class _Args:
    """Tiny shim satisfying ``build_session_filter`` (which reads .days/.model)."""


def _parse_days(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        v = int(raw)
        if v < 0:
            abort(400, description=f"--days must be non-negative, got {v}")
        return v
    except ValueError:
        abort(400, description=f"days must be an integer, got {raw!r}")


def _split_list(raw: str | None) -> list[str]:
    """Parse a comma-separated list from a query param, preserving IDs."""
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


# ── routes ───────────────────────────────────────────────────────────────────

def discovery():
    """GET / — discovery: filter form + recent sessions table + compare basket."""
    days = _parse_days(request.args.get("days"))
    model = request.args.get("model") or None
    final_only = request.args.get("final_only") == "1"

    args = _Args()
    args.days = days
    args.model = model
    where, params = build_session_filter(args)

    conn = get_db()
    sessions = fetch_discovery_sessions(conn, where, params, limit=50)

    return render_template(
        "discovery.html",
        sessions=sessions,
        filters={"days": days, "model": model, "final_only": final_only},
        nav="discover",
    )


def session_report(session_id: str):
    """GET /session/<id> — single-session report."""
    final_only = request.args.get("final_only") == "1"

    conn = get_db()
    # Validate session exists (fetch_session calls sys.exit; intercept).
    try:
        session = fetch_session(conn, session_id)
    except SystemExit:
        abort(404, description=f"Session '{session_id}' not found")

    messages = fetch_assistant_messages(conn, session_id)
    ttft_map = fetch_ttft(conn, session_id)
    data = build_report_data(session, messages, ttft_map, final_only=final_only)

    return render_template("single.html", data=data, final_only=final_only,
                           session_id=session_id, nav="discover")


def aggregate_report():
    """GET /aggregate — aggregate report across filtered sessions."""
    days = _parse_days(request.args.get("days"))
    model = request.args.get("model") or None
    final_only = request.args.get("final_only") == "1"

    args = _Args()
    args.days = days
    args.model = model
    where, params = build_session_filter(args)

    conn = get_db()
    sessions = fetch_matching_sessions(conn, where, params)

    if not sessions:
        return render_template(
            "aggregate.html", data=None, filters={"days": days, "model": model, "final_only": final_only},
            error="No sessions match the given filters.", nav="aggregate",
        )

    session_ids = [s["id"] for s in sessions]
    messages = fetch_aggregate_messages(conn, session_ids)
    ttft_rows = fetch_aggregate_ttft(conn, session_ids, final_only=final_only)

    filter_desc = []
    if days is not None:
        filter_desc.append(f"last {days} days")
    if model is not None:
        filter_desc.append(f"model ~ '{model}'")
    desc = ", ".join(filter_desc) or "all sessions"

    data = build_aggregate_data(sessions, messages, ttft_rows, final_only=final_only)

    return render_template(
        "aggregate.html", data=data, filter_desc=desc, session_count=len(sessions),
        filters={"days": days, "model": model, "final_only": final_only}, nav="aggregate",
    )


def compare_landing():
    """GET /compare — landing for the comparison selector / recent selection."""
    ids = _split_list(request.args.get("ids"))
    # If ids provided, redirect to the sessions comparison route.
    if ids:
        return redirect(url_for("compare_sessions", ids=",".join(ids)))
    return render_template("compare.html", data=None, ctype="sessions",
                            filters={"ids": ""}, nav="compare")


def compare_sessions():
    """GET /compare/sessions?ids=ses_a,ses_b,... (2–4)."""
    ids = _split_list(request.args.get("ids"))
    if len(ids) < 2:
        abort(400, description="Need at least 2 sessions to compare")
    if len(ids) > 4:
        abort(400, description="Can compare at most 4 sessions at once")

    conn = get_db()
    try:
        comparison = build_sessions_comparison(conn, ids)
    except SystemExit:
        abort(404, description="One or more sessions not found")
    except ValueError as e:
        abort(400, description=str(e))

    return render_template("compare.html", data=comparison, ctype="sessions",
                           filters={"ids": request.args.get("ids", "")}, nav="compare")


def compare_models():
    """GET /compare/models?names=mimo,gpt-4,..."""
    names = _split_list(request.args.get("names"))
    if len(names) < 2:
        abort(400, description="Need at least 2 models to compare")

    conn = get_db()
    try:
        comparison = build_models_comparison(conn, names)
    except ValueError as e:
        abort(400, description=str(e))

    return render_template("compare.html", data=comparison, ctype="models",
                           filters={"names": request.args.get("names", "")}, nav="compare")


def compare_days():
    """GET /compare/days?values=7,30,..."""
    raw = _split_list(request.args.get("values"))
    if len(raw) < 2:
        abort(400, description="Need at least 2 date ranges to compare")

    day_ints = []
    for r in raw:
        try:
            day_ints.append(int(r))
        except ValueError:
            abort(400, description=f"'{r}' is not a valid number of days")

    conn = get_db()
    try:
        comparison = build_days_comparison(conn, day_ints)
    except ValueError as e:
        abort(400, description=str(e))

    return render_template("compare.html", data=comparison, ctype="days",
                           filters={"values": request.args.get("values", "")}, nav="compare")
