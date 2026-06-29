"""Smoke tests for the opencode-perf-stats Flask web UI.

Builds a minimal in-memory-shaped SQLite temp DB matching the real opencode.db
schema (session / message / part tables with JSON data columns), then exercises
each route via Flask's test client.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile


# ── fixtures ─────────────────────────────────────────────────────────────────

def _seed_db(path: str) -> None:
    """Create a minimal opencode.db-compatible schema with two sessions."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            title TEXT, agent TEXT, model TEXT, cost REAL,
            tokens_input INTEGER, tokens_output INTEGER,
            tokens_reasoning INTEGER,
            tokens_cache_read INTEGER, tokens_cache_write INTEGER,
            time_created INTEGER, time_updated INTEGER,
            time_compacting INTEGER, metadata TEXT
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
            time_updated INTEGER, data TEXT
        );
        CREATE TABLE part (
            id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
            time_created INTEGER, time_updated INTEGER, data TEXT
        );
        """
    )

    model_json = json.dumps({"id": "test-model", "providerID": "test-provider", "variant": "default"})
    now = 1778522458000

    for i, sid in enumerate(("ses_a", "ses_b"), start=1):
        conn.execute(
            "INSERT INTO session (id,title,agent,model,cost,tokens_input,tokens_output,"
            "tokens_reasoning,tokens_cache_read,tokens_cache_write,time_created,time_updated,"
            "time_compacting,metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, f"Test Session {i}", "build", model_json, 0.05 * i,
             10000 * i, 5000 * i, 1000 * i, 2000 * i, 500 * i,
             now - 3600000 * i, now - 1800000 * i, None, "{}"),
        )
        # three assistant messages per session (to exercise pagination)
        for j in range(1, 4):
            mid = f"msg_{sid}_{j}"
            comp = now + (2000 * j)
            msg_data = json.dumps({
                "role": "assistant",
                "time": {"created": now, "completed": comp},
                "tokens": {"total": 6200 * j, "input": 6000 * j, "output": 200 * j,
                           "reasoning": 10 * j, "cache": {"read": 5 * j, "write": 2 * j}},
                "cost": 0.01 * j, "finish": "stop" if j < 3 else "tool-calls",
                "modelID": "test-model", "providerID": "test-provider",
            })
            conn.execute(
                "INSERT INTO message (id,session_id,time_created,data) VALUES (?,?,?,?)",
                (mid, sid, now + (1000 * j), msg_data),
            )
            # a timed part so TTFT resolves — include text content for the
            # message-parts endpoint exercise.
            part_data = json.dumps({
                "type": "text",
                "time": {"start": now + 500 + (200 * j)},
                "text": f"Hello from message {j} of session {sid}",
            })
            conn.execute(
                "INSERT INTO part (id,message_id,session_id,data) VALUES (?,?,?,?)",
                (f"part_{sid}_{j}", mid, sid, part_data),
            )
            # add a reasoning part for the first message to exercise multi-part
            if j == 1:
                reason_data = json.dumps({
                    "type": "reasoning",
                    "text": f"Let me think about session {sid}...",
                })
                conn.execute(
                    "INSERT INTO part (id,message_id,session_id,data) VALUES (?,?,?,?)",
                    (f"reason_{sid}_{j}", mid, sid, reason_data),
                )
    conn.commit()
    conn.close()


import pytest


@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed_db(db_path)
    from opencode_perf_stats.web import create_app
    return create_app(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


# ── tests ────────────────────────────────────────────────────────────────────

def test_create_app_factory(app):
    """create_app returns a Flask app wired to the temp DB."""
    assert app.config["DB_PATH"].endswith("test.db")
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "discovery" in endpoints
    assert "session_report" in endpoints
    assert "aggregate" in endpoints
    assert "trends" in endpoints
    assert "compare_sessions" in endpoints


def test_discovery_route(client):
    """GET / returns 200 with nav, a session table, and a model datalist."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "opencode-perf-stats" in body
    assert "Discover" in body
    assert "ses_a" in body  # session id appears in the table
    # Model filter is pre-populated with a datalist of distinct models.
    assert 'id="model-list"' in body
    assert 'list="model-list"' in body
    assert "test-provider/test-model" in body


def test_discovery_filter(client):
    """GET /?model=... filters sessions."""
    r = client.get("/?model=test-model")
    assert r.status_code == 200
    assert "ses_a" in r.get_data(as_text=True)


def test_session_route(client):
    """GET /session/<id> renders the single-session report with charts."""
    r = client.get("/session/ses_a")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Session Report" in body
    assert "canvas" in body  # Chart.js canvas present
    assert "test-model" in body
    # Pagination controls present
    assert 'id="per-page"' in body
    assert 'id="prev-page"' in body
    assert 'id="next-page"' in body
    assert 'id="msg-tbody"' in body
    assert 'value="20"' in body
    assert 'value="50"' in body
    assert 'value="100"' in body
    # Row-clickable + message-id attributes
    assert 'class="msg-data-row row-clickable"' in body
    assert 'data-message-id=' in body
    # Expandable detail rows
    assert 'class="msg-detail-row"' in body
    assert 'msg-detail-grid' in body
    # app.js script included
    assert 'src="' in body and 'app.js' in body
    # fmt_ts filter available (template global)
    assert "Created" in body and "Completed" in body


def test_session_report_extended_payload(client):
    """The REPORT JSON embedded in the page includes extra per-message fields."""
    r = client.get("/session/ses_a")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Extended tps_detail fields present in the JSON
    assert '"input_tokens"' in body
    assert '"reasoning_tokens"' in body
    assert '"cache_read"' in body
    assert '"cache_write"' in body
    assert '"cost"' in body
    assert '"model_id"' in body
    assert '"provider_id"' in body
    assert '"created_ms"' in body
    assert '"completed_ms"' in body
    # Detail values rendered in expansion rows
    assert "Cost" in body
    assert "Input Tokens" in body
    assert "Cache Read" in body
    assert "Cache Write" in body


def test_session_final_only_toggle(client):
    """GET /session/<id>?final_only=1 also renders."""
    r = client.get("/session/ses_a?final_only=1")
    assert r.status_code == 200


def test_session_not_found_404(client):
    """GET /session/<missing> returns 404, not a crash."""
    r = client.get("/session/does_not_exist")
    assert r.status_code == 404


def test_aggregate_route(client):
    """GET /aggregate renders the aggregate report with a model datalist."""
    r = client.get("/aggregate")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Aggregate Report" in body
    assert "canvas" in body
    assert 'id="model-list"' in body
    assert 'list="model-list"' in body


def test_compare_landing(client):
    """GET /compare renders the server-rendered comparison pickers.

    Verifies the two tabbed pickers are present and server-rendered (no
    client-side fetch): sessions list and models list.
    """
    r = client.get("/compare")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Tab selector present
    assert "compare-tabs" in body
    # Sessions picker: server-rendered list with both seeded sessions
    assert 'id="session-list"' in body
    assert "ses_a" in body
    assert "ses_b" in body
    assert 'data-basket="sessions"' in body
    # Models picker: distinct provider/model identity rendered server-side
    assert 'id="model-list"' in body
    assert "test-provider/test-model" in body
    assert 'data-basket="models"' in body
    # Date-range picker is removed (replaced by /trends).
    assert 'id="panel-days"' not in body
    assert "day-check" not in body
    assert "Date Ranges" not in body
    # Session-picker model filter has a pre-populated datalist.
    assert 'id="ps-model-list"' in body
    assert 'list="ps-model-list"' in body


def test_compare_no_api_routes(client):
    """The client-side /api/* picker routes are removed in favour of
    server-rendered lists."""
    assert client.get("/api/models").status_code == 404
    assert client.get("/api/sessions").status_code == 404


def test_compare_landing_session_filter(client):
    """GET /compare?days=&model= scopes the sessions picker list."""
    r = client.get("/compare?model=test-provider/test-model")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "ses_a" in body
    # Scoping to a non-matching model hides both sessions.
    r2 = client.get("/compare?model=does-not-exist")
    assert r2.status_code == 200
    assert "ses_a" not in r2.get_data(as_text=True)


def test_compare_sessions_picker_reflects_active(client):
    """GET /compare/sessions?ids=... pre-checks the active session selection."""
    r = client.get("/compare/sessions?ids=ses_a,ses_b")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Both active ids are checked in the picker.
    assert body.count('checked') >= 2
    assert 'value="ses_a"' in body
    assert 'value="ses_b"' in body


def test_compare_models_picker_reflects_active(client):
    """GET /compare/models?names=... pre-checks the active model identity.

    The picker lists distinct models from the DB, so a non-matching name
    (``nonexistent``) is not a checkbox — only the real identity is.
    """
    r = client.get("/compare/models?names=test-provider/test-model,nonexistent")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'value="test-provider/test-model"' in body
    assert 'value="nonexistent"' not in body  # no matching model → no checkbox
    # The identity checkbox is pre-checked (active selection).
    assert body.count("checked") >= 1


def test_compare_sessions_ok(client):
    """GET /compare/sessions?ids=ses_a,ses_b renders the comparison."""
    r = client.get("/compare/sessions?ids=ses_a,ses_b")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "canvas" in body
    assert "Side-by-side" in body


def test_compare_sessions_too_few_400(client):
    """GET /compare/sessions with one id returns 400."""
    r = client.get("/compare/sessions?ids=ses_a")
    assert r.status_code == 400


def test_compare_models(client):
    """GET /compare/models resolves labels to full provider/model identity.

    Even when filtered by a bare model-ID substring (``test-model``), the
    comparison column header shows the resolved ``test-provider/test-model``
    identity rather than the raw search substring.
    """
    r = client.get("/compare/models?names=test-model,nonexistent")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "canvas" in body
    # The resolved identity appears as a comparison column, not the raw
    # substring "test-model" alone.
    assert "test-provider/test-model" in body
    # The empty-match item keeps the raw input as its label.
    assert "nonexistent" in body


def test_compare_models_full_identity(client):
    """GET /compare/models with full provider/model identities resolves
    cleanly and the identity appears in both results table and picker."""
    r = client.get("/compare/models?names=test-provider/test-model,nonexistent")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "test-provider/test-model" in body


def test_build_models_comparison_resolves_identity(app):
    """build_models_comparison resolves labels to provider/model identity.

    A bare substring input (``test-model``) resolves to the full
    ``test-provider/test-model`` identity present in matched sessions; a
    non-matching input keeps the raw string with session_count=0.
    """
    db_path = app.config["DB_PATH"]
    from opencode_perf_stats.db import connect
    from opencode_perf_stats.compare import build_models_comparison
    conn = connect(db_path)
    try:
        result = build_models_comparison(conn, ["test-model", "nonexistent"])
    finally:
        conn.close()
    assert result["type"] == "models"
    assert result["count"] == 2
    matched, empty = result["items"]
    # Matched item: label/model resolved to the full identity.
    assert matched["label"] == "test-provider/test-model"
    assert matched["model"] == "test-provider/test-model"
    assert matched["session_count"] > 0
    # Empty-match item: keeps raw input, zero sessions.
    assert empty["label"] == "nonexistent"
    assert empty["session_count"] == 0


def test_build_models_comparison_full_identity_input(app):
    """Passing a full provider/model identity resolves to itself."""
    db_path = app.config["DB_PATH"]
    from opencode_perf_stats.db import connect
    from opencode_perf_stats.compare import build_models_comparison
    conn = connect(db_path)
    try:
        result = build_models_comparison(
            conn, ["test-provider/test-model", "missing/provider"]
        )
    finally:
        conn.close()
    matched, empty = result["items"]
    assert matched["label"] == "test-provider/test-model"
    assert empty["label"] == "missing/provider"
    assert empty["session_count"] == 0


def test_compare_days_route_removed(client):
    """GET /compare/days is removed (date-range comparison moved to /trends)."""
    r = client.get("/compare/days?values=7,30")
    assert r.status_code == 404


def test_serve_subcommand_in_help():
    """`serve` is listed in the CLI help."""
    result = subprocess.run(
        [sys.executable, "-m", "opencode_perf_stats", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "serve" in result.stdout
    assert "Web UI" in result.stdout


def test_serve_subcommand_help():
    """`serve --help` documents its flags."""
    result = subprocess.run(
        [sys.executable, "-m", "opencode_perf_stats", "serve", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--port" in result.stdout
    assert "--host" in result.stdout
    assert "--no-browser" in result.stdout


# ── trends (/trends) ─────────────────────────────────────────────────────────


def test_trends_route_default(client):
    """GET /trends defaults to a 30-day window and day period.

    The form defaults are rendered in both the empty and chart branches, so we
    assert them here regardless of whether the (fixed-timestamp) seed falls
    inside the default 30-day window.
    """
    r = client.get("/trends")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Time Analysis" in body
    # Default days value is 30.
    assert 'value="30"' in body
    # Default period is day (pre-selected).
    assert 'value="day" selected' in body
    # Period selector with all four granularities.
    assert 'name="period"' in body
    assert 'value="week"' in body
    assert 'value="month"' in body
    assert 'value="year"' in body
    # Nav entry present.
    assert "Trends" in body  # nav link text
    # Model filter is pre-populated with a datalist.
    assert 'id="model-list"' in body
    assert 'list="model-list"' in body


def test_trends_renders_charts(client):
    """GET /trends?days= (window cleared) renders buckets + per-model charts.

    The seed fixture uses a fixed ``now`` that drifts relative to real time, so
    we clear the day window (?days=) to guarantee the seeded sessions fall
    inside the query and the chart payload is emitted.
    """
    r = client.get("/trends?days=")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "canvas" in body  # Chart.js canvases present
    assert 'id="tpsChart"' in body
    assert 'id="costChart"' in body
    assert 'id="sessionsChart"' in body
    assert 'id="messagesChart"' in body
    # Per-chart toggles + master toggle present.
    assert "chart-toggle-check" in body
    assert "toggle-all-charts" in body
    # Embedded data payload (buckets + per-model series present).
    assert '"buckets"' in body
    assert '"by_model"' in body


def test_trends_period_week(client):
    """GET /trends?period=week renders and echoes the week period."""
    r = client.get("/trends?period=week&days=")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Week option pre-selected.
    assert 'value="week" selected' in body
    assert '"period": "week"' in body


def test_trends_period_month_and_year(client):
    """GET /trends?period=month / year render without error."""
    for p in ("month", "year"):
        r = client.get(f"/trends?period={p}&days=")
        assert r.status_code == 200
        assert f'"period": "{p}"' in r.get_data(as_text=True)


def test_trends_invalid_period_400(client):
    """GET /trends?period=bogus returns 400."""
    r = client.get("/trends?period=bogus")
    assert r.status_code == 400


def test_trends_empty_filter(client):
    """GET /trends?model=does-not-exist renders the empty state (200, no chart)."""
    r = client.get("/trends?model=does-not-exist")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "No sessions match" in body
    # No embedded data payload on the empty branch.
    assert '"buckets"' not in body


def test_trends_explicit_all_days(client):
    """GET /trends?days= (empty) disables the 30-day default → all sessions."""
    r = client.get("/trends?days=")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '"buckets"' in body
    assert "all sessions" in body  # filter_desc falls back to "all sessions"


def test_trends_final_only(client):
    """GET /trends?final_only=1 renders without error (window cleared)."""
    r = client.get("/trends?days=&final_only=1")
    assert r.status_code == 200
    assert '"final_only": true' in r.get_data(as_text=True)


def test_build_time_series_returns_locked_schema(app):
    """build_time_series returns the locked dict schema with per-model buckets."""
    db_path = app.config["DB_PATH"]
    from opencode_perf_stats.db import connect, build_session_filter
    from opencode_perf_stats.trends import build_time_series
    conn = connect(db_path)
    try:
        # No filter → all sessions.
        where, params = build_session_filter(type("A", (), {"days": None, "model": None})())
        result = build_time_series(conn, where, params, "day", final_only=False)
    finally:
        conn.close()
    assert result["period"] == "day"
    assert result["final_only"] is False
    assert result["session_count"] == 2
    assert result["message_count"] > 0
    assert isinstance(result["models"], list)
    assert "test-provider/test-model" in result["models"]
    assert isinstance(result["buckets"], list)
    assert result["buckets"], "expected at least one day bucket"
    # Buckets sorted ascending and each carries the locked metric keys.
    labels = [b["label"] for b in result["buckets"]]
    assert labels == sorted(labels)
    b0 = result["buckets"][0]
    for key in (
        "label", "session_count", "message_count",
        "tps_p50", "tps_p95", "ttft_p50", "ttft_p95",
        "tokens_input", "tokens_output", "tokens_reasoning", "tokens_total",
        "cost", "by_model",
    ):
        assert key in b0, f"missing bucket key: {key}"
    # Per-model breakdown keyed by provider/model identity.
    assert isinstance(b0["by_model"], dict)
    assert "test-provider/test-model" in b0["by_model"]
    mdl = b0["by_model"]["test-provider/test-model"]
    assert mdl["session_count"] >= 1


def test_build_time_series_invalid_period(app):
    """build_time_series rejects an unknown period with ValueError."""
    db_path = app.config["DB_PATH"]
    from opencode_perf_stats.db import connect
    from opencode_perf_stats.trends import build_time_series
    conn = connect(db_path)
    try:
        with pytest.raises(ValueError):
            build_time_series(conn, "", [], "hour", final_only=False)
    finally:
        conn.close()


def test_cli_compare_days_choice_removed():
    """`compare days` is no longer a valid subcommand (removed)."""
    result = subprocess.run(
        [sys.executable, "-m", "opencode_perf_stats", "compare", "days", "7", "30"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "invalid choice" in result.stderr.lower() or "days" in result.stderr.lower()


def test_cli_compare_help_lists_sessions_models_only():
    """`compare --help` omits 'days' from the type choices."""
    result = subprocess.run(
        [sys.executable, "-m", "opencode_perf_stats", "compare", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "sessions" in result.stdout
    assert "models" in result.stdout
    # 'days' should not appear as a documented choice.
    combined = result.stdout + result.stderr
    assert "days" not in combined


# ── message content modal (/session/<sid>/message/<mid>/parts) ──────────────


def test_message_parts_endpoint_returns_200(client):
    """GET /session/ses_a/message/msg_ses_a_1/parts returns JSON with parts."""
    r = client.get("/session/ses_a/message/msg_ses_a_1/parts")
    assert r.status_code == 200
    data = r.get_json()
    assert "parts" in data
    assert len(data["parts"]) >= 1
    # First part is text with content.
    text_parts = [p for p in data["parts"] if p["type"] == "text"]
    assert len(text_parts) >= 1
    assert "message 1" in text_parts[0]["text"]


def test_message_parts_endpoint_has_reasoning_part(client):
    """GET /session/ses_a/message/msg_ses_a_1/parts includes the reasoning part."""
    r = client.get("/session/ses_a/message/msg_ses_a_1/parts")
    assert r.status_code == 200
    parts = r.get_json()["parts"]
    reasoning = [p for p in parts if p["type"] == "reasoning"]
    assert len(reasoning) == 1
    assert "think about session ses_a" in reasoning[0]["text"]


def test_message_parts_cross_session_404(client):
    """GET /session/ses_b/message/msg_ses_a_1/parts returns 404 (wrong session)."""
    r = client.get("/session/ses_b/message/msg_ses_a_1/parts")
    assert r.status_code == 404


def test_message_parts_missing_message_404(client):
    """GET /session/ses_a/message/msg_does_not_exist/parts returns 404."""
    r = client.get("/session/ses_a/message/msg_does_not_exist/parts")
    assert r.status_code == 404


def test_session_report_has_view_message_button(client):
    """Session report page includes the 'View message content' button."""
    r = client.get("/session/ses_a")
    body = r.get_data(as_text=True)
    assert "msg-content-btn" in body
    assert "View message content" in body


def test_session_report_has_data_session_id(client):
    """Session report page has data-session-id on #msg-table-wrap."""
    r = client.get("/session/ses_a")
    body = r.get_data(as_text=True)
    assert 'data-session-id="ses_a"' in body


def test_message_parts_in_app_endpoints(app):
    """message_parts endpoint is registered in the Flask app."""
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "message_parts" in endpoints
