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
        # one assistant message with timing + a first-token part
        mid = f"msg_{sid}"
        msg_data = json.dumps({
            "role": "assistant",
            "time": {"created": now, "completed": now + 2000},
            "tokens": {"total": 6200, "input": 6000, "output": 200,
                       "reasoning": 0, "cache": {"read": 0, "write": 0}},
            "cost": 0.01, "finish": "stop",
            "modelID": "test-model", "providerID": "test-provider",
        })
        conn.execute(
            "INSERT INTO message (id,session_id,time_created,data) VALUES (?,?,?,?)",
            (mid, sid, now, msg_data),
        )
        # a timed part so TTFT resolves
        part_data = json.dumps({"type": "text", "time": {"start": now + 500}})
        conn.execute(
            "INSERT INTO part (id,message_id,session_id,data) VALUES (?,?,?,?)",
            (f"part_{sid}", mid, sid, part_data),
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
    assert "compare_sessions" in endpoints


def test_discovery_route(client):
    """GET / returns 200 with nav and a session table."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "opencode-perf-stats" in body
    assert "Discover" in body
    assert "ses_a" in body  # session id appears in the table


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


def test_session_final_only_toggle(client):
    """GET /session/<id>?final_only=1 also renders."""
    r = client.get("/session/ses_a?final_only=1")
    assert r.status_code == 200


def test_session_not_found_404(client):
    """GET /session/<missing> returns 404, not a crash."""
    r = client.get("/session/does_not_exist")
    assert r.status_code == 404


def test_aggregate_route(client):
    """GET /aggregate renders the aggregate report."""
    r = client.get("/aggregate")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Aggregate Report" in body
    assert "canvas" in body


def test_compare_landing(client):
    """GET /compare renders the comparison selector form."""
    r = client.get("/compare")
    assert r.status_code == 200
    assert "cmp-type" in r.get_data(as_text=True)


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
    """GET /compare/models renders even when one model has no sessions."""
    r = client.get("/compare/models?names=test-model,nonexistent")
    assert r.status_code == 200
    assert "canvas" in r.get_data(as_text=True)


def test_compare_days(client):
    """GET /compare/days renders a date-range comparison."""
    r = client.get("/compare/days?values=7,30")
    assert r.status_code == 200


def test_compare_days_invalid_400(client):
    """GET /compare/days with a non-integer returns 400."""
    r = client.get("/compare/days?values=7,notanumber")
    assert r.status_code == 400


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
