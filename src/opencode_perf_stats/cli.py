"""CLI entry point for opencode-perf-stats."""

import argparse
import json
import sys

from . import __version__
from .db import (
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
)
from .formatting import fmt_ts
from .reports.markdown import (
    build_report_data,
    render_markdown,
    cmd_list,
    build_aggregate_data,
    render_aggregate_markdown,
    cmd_aggregate,
)
from .reports.html import render_single_html, render_aggregate_html


# ── main dispatch ────────────────────────────────────────────────────────────

def main() -> None:
    # Pre-check: if 'compare' or 'serve' is the first arg, handle as a subcommand.
    # This avoids argparse treating them as a session_id.
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        _handle_compare_command()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        _handle_serve_command()
        return

    parser = argparse.ArgumentParser(
        prog="opencode-perf-stats",
        description=(
            "Performance analytics for OpenCode sessions (TPS, TTFT, tokens, duration).\n\n"
            "Modes:\n"
            "  1. Single-session: pass a session_id, or pass nothing for the most recent.\n"
            "  2. Aggregate: pass --days and/or --model with NO session_id.\n"
            "  3. Discovery: --list prints recent sessions and exits.\n"
            "  4. Compare: compare sessions or models.\n"
            "  5. Web UI: `serve` launches an interactive browser UI (requires the [web] extra).\n\n"
            "Precedence: explicit session_id > --list > aggregate (filters present).\n"
            "If no session_id and no filters: reports on the most recent session."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Database: $XDG_DATA_HOME/opencode/opencode.db\n\n"
            "Examples:\n"
            "  opencode-perf-stats                              # most recent session\n"
            "  opencode-perf-stats ses_xxx                      # specific session\n"
            "  opencode-perf-stats --days 7                     # aggregate, last 7 days\n"
            "  opencode-perf-stats --days 7 --model mimo        # aggregate, model filter\n"
            "  opencode-perf-stats --list                       # discovery table\n"
            "  opencode-perf-stats --html                       # interactive HTML report\n"
            "  opencode-perf-stats --days 7 --html              # aggregate HTML report\n"
            "  opencode-perf-stats compare sessions ses_a ses_b # compare sessions\n"
            "  opencode-perf-stats serve                        # launch web UI (needs [web] extra)\n"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "session_id",
        nargs="?",
        help="session ID (default: most recently updated session). "
             "Takes precedence over --days/--model/--list.",
    )
    parser.add_argument(
        "--final-only",
        action="store_true",
        dest="final_only",
        help="only include messages where finish='stop' (final answers, not tool-calls). "
             "Applies to single-session and aggregate modes.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="output as JSON instead of Markdown",
    )
    parser.add_argument(
        "--html",
        nargs="?",
        const="-",
        default=None,
        dest="html",
        metavar="FILE",
        help="generate an interactive HTML report with Chart.js. "
             "Writes to FILE if given, stdout if '-', or auto-names the file.",
    )
    parser.add_argument(
        "--db",
        help="path to opencode.db (default: auto-resolved from XDG_DATA_HOME)",
    )
    parser.add_argument(
        "--days",
        type=int,
        dest="days",
        help="filter to sessions created in the last N days. "
             "Triggers aggregate mode when no session_id is given.",
    )
    parser.add_argument(
        "--model",
        dest="model",
        help="filter by model ID substring (case-insensitive). "
             "Triggers aggregate mode when no session_id is given.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list",
        help="list recent sessions (discovery), then exit. Honors --days/--model. "
             "OVERRIDE: an explicit session_id takes precedence and ignores --list.",
    )

    args = parser.parse_args()

    db_path = args.db or resolve_db_path()
    conn = connect(db_path)

    try:
        # ── dispatch priority ──
        # 1. explicit session_id → single-session report
        # 2. --list → discovery table
        # 3. --days or --model present + no session_id → aggregate mode
        # 4. nothing → most recent session (single-session report)

        if args.session_id:
            if args.list or args.days is not None or args.model is not None:
                sys.stderr.write(
                    "note: explicit session_id takes precedence over --list/--days/--model; "
                    "producing single-session report.\n"
                )
            _run_single(conn, args)
        elif args.list:
            where, params = build_session_filter(args)
            cmd_list(conn, where, params, args.json)
        elif args.days is not None or args.model is not None:
            _run_aggregate(conn, args)
        else:
            # No session_id and no filters → most recent session.
            _run_single(conn, args)
    finally:
        conn.close()


def _handle_compare_command() -> None:
    """Handle the compare subcommand separately."""
    parser = argparse.ArgumentParser(
        prog="opencode-perf-stats compare",
        description="Compare sessions or models",
    )
    parser.add_argument(
        "type",
        choices=["sessions", "models"],
        help="what to compare",
    )
    parser.add_argument(
        "values",
        nargs="+",
        help="IDs, model names, or dates to compare",
    )
    parser.add_argument(
        "--html",
        nargs="?",
        const="-",
        default=None,
        dest="compare_html",
        metavar="FILE",
        help="generate comparison HTML report",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="compare_json",
        help="output comparison as JSON",
    )
    parser.add_argument(
        "--db",
        help="path to opencode.db",
    )

    # Skip the 'compare' argument in sys.argv
    args = parser.parse_args(sys.argv[2:])
    _run_compare(args)


def _handle_serve_command() -> None:
    """Handle the `serve` subcommand: launch the Flask web UI.

    Requires the ``web`` optional dependency (``flask``). Install with
    ``pip install -e ".[web]"``.
    """
    parser = argparse.ArgumentParser(
        prog="opencode-perf-stats serve",
        description="Launch the web UI (interactive reports in your browser).",
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="port to bind (default: 5000)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="interface to bind (default: 127.0.0.1; WARNING: non-loopback is insecure)",
    )
    parser.add_argument(
        "--db", help="path to opencode.db (default: auto-resolved from XDG_DATA_HOME)",
    )
    parser.add_argument(
        "--no-browser", action="store_true", dest="no_browser",
        help="do not auto-open the browser",
    )
    args = parser.parse_args(sys.argv[2:])

    try:
        from .web import create_app
    except ImportError:
        sys.stderr.write(
            "error: the 'serve' subcommand requires Flask. "
            "Install with: pip install -e \".[web]\"\n"
        )
        sys.exit(1)

    db_path = args.db or resolve_db_path()
    app = create_app(db_path)

    if args.host != "127.0.0.1" and args.host != "localhost":
        sys.stderr.write(
            f"warning: binding to {args.host} — no auth/CSRF protection. "
            "This is insecure for non-loopback hosts.\n"
        )

    url = f"http://{args.host}:{args.port}/"
    sys.stderr.write(f"opencode-perf-stats web UI: {url}\n")
    sys.stderr.write(f"  db: {db_path}\n")
    sys.stderr.write("  (Ctrl+C to stop)\n")

    if not args.no_browser:
        import webbrowser
        import threading
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        app.run(host=args.host, port=args.port, debug=False)
    except OSError as e:
        if "Address already in use" in str(e) or "98" in str(e):
            sys.stderr.write(
                f"error: port {args.port} is already in use. "
                f"Try: opencode-perf-stats serve --port {args.port + 1}\n"
            )
            sys.exit(1)
        raise


def _run_single(conn, args) -> None:
    """Execute single-session report path."""
    session_id = get_session_id(conn, args.session_id)
    session = fetch_session(conn, session_id)
    messages = fetch_assistant_messages(conn, session_id)
    ttft_map = fetch_ttft(conn, session_id)

    data = build_report_data(session, messages, ttft_map, args.final_only)

    if args.html is not None:
        html = render_single_html(data)
        _write_html(html, args.html, f"opencode-perf-stats-{session_id[:16]}.html")
    elif args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        if not args.session_id:
            print(f"_Auto-selected most recent session: `{session_id}`_\n")
        print(render_markdown(data))


def _run_aggregate(conn, args) -> None:
    """Execute multi-session aggregate path."""
    where, params = build_session_filter(args)

    sessions = fetch_matching_sessions(conn, where, params)
    if not sessions:
        if args.json:
            print(json.dumps({"error": "no sessions match the given filters"}, indent=2))
        else:
            print("(no sessions match the given filters)")
        return

    session_ids = [s["id"] for s in sessions]
    messages = fetch_aggregate_messages(conn, session_ids)
    ttft_rows = fetch_aggregate_ttft(conn, session_ids, args.final_only)

    filter_desc = []
    if args.days is not None:
        filter_desc.append(f"last {args.days} days")
    if args.model is not None:
        filter_desc.append(f"model ~ '{args.model}'")
    desc = ", ".join(filter_desc) or "all sessions"

    data = build_aggregate_data(sessions, messages, ttft_rows, args.final_only)

    if args.html is not None:
        html = render_aggregate_html(data, desc)
        _write_html(html, args.html, "opencode-perf-stats-aggregate.html")
    elif args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(f"_Aggregate mode: {desc} "
              f"— {len(sessions)} session(s), {len(messages)} message(s)_\n")
        print(render_aggregate_markdown(data))


def _run_compare(args) -> None:
    """Execute comparison mode (stub — raises NotImplementedError)."""
    # Import here to avoid circular imports at module level
    from .compare import run_compare
    run_compare(args)


def _write_html(html: str, path: str, default_name: str) -> None:
    """Write HTML to file or stdout."""
    if path == "-":
        print(html)
    else:
        filename = path if path != "-" else default_name
        with open(filename, "w") as f:
            f.write(html)
        sys.stderr.write(f"HTML report written to {filename}\n")
