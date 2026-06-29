"""Smoke tests for opencode-perf-stats."""

import subprocess
import sys
import importlib


def test_import():
    """Package imports without error."""
    import opencode_perf_stats
    assert hasattr(opencode_perf_stats, "__version__")
    assert opencode_perf_stats.__version__ == "0.1.0"


def test_submodules_import():
    """All submodules import without error."""
    from opencode_perf_stats import db
    from opencode_perf_stats import formatting
    from opencode_perf_stats.reports import markdown
    from opencode_perf_stats.reports import html
    from opencode_perf_stats import compare

    assert callable(db.resolve_db_path)
    assert callable(db.connect)
    assert callable(formatting.fmt_ts)
    assert callable(formatting.fmt_duration)
    assert callable(formatting.fmt_tokens)
    assert callable(formatting.aggregate)
    assert callable(markdown.build_report_data)
    assert callable(markdown.render_markdown)
    assert callable(html.render_single_html)
    assert callable(html.render_aggregate_html)


def test_formatting_helpers():
    """Test formatting functions produce expected output."""
    from opencode_perf_stats.formatting import fmt_ts, fmt_duration, fmt_tokens, aggregate

    # fmt_ts
    assert fmt_ts(None) == "—"
    assert "2024" in fmt_ts(1704067200000)  # 2024-01-01 00:00:00 UTC

    # fmt_duration
    assert fmt_duration(None) == "—"
    assert fmt_duration(30.5) == "30.5s"
    assert fmt_duration(90) == "1m 30s"
    assert fmt_duration(3661) == "1h 1m 1s"

    # fmt_tokens
    assert fmt_tokens(500) == "500"
    assert fmt_tokens(1500) == "1.5K"
    assert fmt_tokens(2500000) == "2.5M"

    # aggregate
    assert aggregate([]) == {"count": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None, "low_n": False}
    result = aggregate([10, 20, 30])
    assert result["count"] == 3
    assert result["mean"] == 20.0
    assert result["median"] == 20.0
    assert result["min"] == 10.0
    assert result["max"] == 30.0


def test_html_generation_single():
    """HTML report generator produces valid HTML with Chart.js."""
    from opencode_perf_stats.reports.html import render_single_html

    mock_data = {
        "session": {
            "id": "test_session",
            "title": "Test Session",
            "agent": "build",
            "model": "test-model",
            "provider": "test-provider",
            "variant": None,
            "created": "2024-01-01 00:00:00 UTC",
            "updated": "2024-01-01 01:00:00 UTC",
            "duration_seconds": 3600.0,
            "time_compacting": None,
            "metadata": None,
        },
        "tokens": {
            "input": 10000,
            "output": 5000,
            "reasoning": 2000,
            "cache_read": 3000,
            "cache_write": 1000,
            "cache_hit_pct": 23.1,
            "cost": 0.05,
        },
        "messages": {
            "total_assistant": 10,
            "with_timing": 8,
            "incomplete": 2,
            "finish_stop": 6,
            "finish_tool_calls": 4,
            "filter": "all assistant messages with timing",
        },
        "tps": {
            "detail": [
                {"message_id": "msg1", "tps": 50.0, "output_tokens": 100, "duration_ms": 2000, "finish": "stop", "low_confidence": False, "low_confidence_reason": None},
            ],
            "aggregate": {"count": 1, "mean": 50.0, "median": 50.0, "min": 50.0, "max": 50.0},
        },
        "ttft": {
            "detail": [
                {"message_id": "msg1", "ttft_ms": 500, "first_token_type": "text", "output_tokens": 100, "finish": "stop"},
            ],
            "aggregate": {"count": 1, "mean": 500.0, "median": 500.0, "min": 500.0, "max": 500.0},
        },
    }

    html = render_single_html(mock_data)
    assert "<!DOCTYPE html>" in html
    assert "chart.js" in html.lower()
    assert "<canvas" in html
    assert "Test Session" in html
    assert "test-model" in html


def test_html_generation_aggregate():
    """Aggregate HTML report generator produces valid HTML."""
    from opencode_perf_stats.reports.html import render_aggregate_html

    mock_data = {
        "overview": {
            "session_count": 5,
            "message_count": 50,
            "filter": "all assistant messages with timing",
        },
        "tokens": {
            "input": 100000,
            "output": 50000,
            "cache_read": 30000,
            "cache_hit_pct": 23.1,
            "cost": 0.5,
        },
        "tps": {
            "aggregate": {"count": 40, "mean": 45.0, "median": 42.0, "p95": 75.0, "min": 10.0, "max": 80.0, "low_n": False},
            "note": "excludes low-confidence messages",
        },
        "ttft": {
            "aggregate": {"count": 40, "mean": 600.0, "median": 550.0, "p95": 1300.0, "min": 200.0, "max": 1500.0, "low_n": False},
        },
        "per_model": [
            {"model": "test-provider/test-model", "messages": 40, "output_tokens": 50000,
             "tps_mean": 45.0, "tps_median": 42.0, "tps_p50": 42.0, "tps_p95": 75.0, "tps_low_n": False,
             "ttft_mean": 600.0, "ttft_median": 550.0, "ttft_p50": 550.0, "ttft_p95": 1300.0, "ttft_low_n": False,
             "cost": 0.5},
        ],
        "top_sessions": [
            {"id": "ses1", "title": "Test", "model": "test-provider/test-model", "output_tokens": 10000, "cost": 0.1, "duration_seconds": 600.0},
        ],
    }

    html = render_aggregate_html(mock_data, "last 7 days")
    assert "<!DOCTYPE html>" in html
    assert "chart.js" in html.lower()
    assert "<canvas" in html
    assert "last 7 days" in html


def test_cli_help():
    """CLI --help exits 0 and shows usage."""
    result = subprocess.run(
        [sys.executable, "-m", "opencode_perf_stats", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "opencode-perf-stats" in result.stdout
    assert "--html" in result.stdout
    assert "compare" in result.stdout


def test_cli_version():
    """CLI --version shows version."""
    result = subprocess.run(
        [sys.executable, "-m", "opencode_perf_stats", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


def test_compare_sessions_validation():
    """Compare sessions requires at least 2 sessions."""
    result = subprocess.run(
        [sys.executable, "-m", "opencode_perf_stats", "compare", "sessions", "ses_only_one"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "at least 2" in result.stderr
