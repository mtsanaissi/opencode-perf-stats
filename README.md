# opencode-perf-stats

Performance analytics for [OpenCode](https://opencode.ai) sessions — TPS, TTFT, tokens, cost, and comparisons.

## Install

```bash
pip install opencode-perf-stats
```

Or with [pipx](https://pypa.github.io/pipx/) (recommended for CLI tools):

```bash
pipx install opencode-perf-stats
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uvx opencode-perf-stats --help
```

## Quick Start

```bash
# Most recent session (default)
opencode-perf-stats

# Specific session
opencode-perf-stats ses_104b144f3ffe2Arh...

# Aggregate over last 7 days
opencode-perf-stats --days 7

# Filter by model
opencode-perf-stats --days 7 --model mimo

# Interactive HTML report
opencode-perf-stats --html

# Aggregate HTML report
opencode-perf-stats --days 7 --html report.html

# List recent sessions
opencode-perf-stats --list

# JSON output
opencode-perf-stats --json
```

## Modes

### Single-Session (default)

Reports TPS, TTFT, reasoning TTFT, session duration, and token/cost breakdown for one session.

```bash
opencode-perf-stats                         # most recently updated session
opencode-perf-stats ses_abc123              # specific session
opencode-perf-stats --final-only            # only finish='stop' messages
```

### Aggregate

Aggregates TPS/TTFT/tokens across all matching sessions, with per-model breakdown.

```bash
opencode-perf-stats --days 7                # last 7 days
opencode-perf-stats --days 30 --model mimo  # filtered by model
opencode-perf-stats --days 7 --json         # JSON output
```

### Discovery

List recent sessions with IDs, titles, and metadata.

```bash
opencode-perf-stats --list                  # recent sessions table
opencode-perf-stats --list --days 7 --json  # filtered, JSON
```

### Comparison (experimental)

Compare sessions, models, or date ranges side by side.

```bash
# Compare up to 4 sessions
opencode-perf-stats compare sessions ses_a ses_b ses_c ses_d

# Compare models
opencode-perf-stats compare models mimo gpt-4 claude

# Compare date ranges
opencode-perf-stats compare days 7 30

# JSON output
opencode-perf-stats compare sessions ses_a ses_b --json
```

## HTML Reports

Generate self-contained HTML reports with interactive Chart.js charts:

```bash
# Single-session HTML report
opencode-perf-stats --html

# Aggregate HTML report
opencode-perf-stats --days 7 --html report.html

# Write to stdout
opencode-perf-stats --html -
```

Charts include:
- **TPS per message** — bar chart with low-confidence markers
- **TTFT per message** — time to first token visualization
- **Token breakdown** — doughnut chart (input/output/reasoning/cache)
- **Message summary** — final vs tool-calls vs incomplete
- **Per-model comparison** — grouped bars (aggregate mode)
- **Top sessions** — horizontal bar chart (aggregate mode)

## Web UI

An interactive browser UI covers all four modes with modern, intuitive UX:
session discovery, single-session reports, aggregate views, and side-by-side
comparison. Requires the optional `web` extra:

```bash
pip install -e ".[web]"      # or: pip install "opencode-perf-stats[web]"
opencode-perf-stats serve    # opens http://127.0.0.1:5000/ in your browser
```

The UI reuses the same dark theme and Chart.js charts as the standalone HTML
reports. Features:

- **Discover (`/`)** — filter by days/model, click a row to open a session,
  checkbox-select 2–4 sessions and use the sticky "Compare selected" basket.
- **Aggregate (`/aggregate`)** — TPS/TTFT/tokens/cost across filtered sessions
  with per-model charts and top-sessions tables.
- **Compare (`/compare`)** — compare sessions, models, or date ranges
  side-by-side with grouped bar charts and a comparison table.
- **Single session (`/session/<id>`)** — full report with TPS/TTFT/token
  charts and a per-message detail table; `final_only` toggle.

```bash
opencode-perf-stats serve --port 5001      # custom port
opencode-perf-stats serve --no-browser     # don't auto-open a browser
opencode-perf-stats serve --db /path/to/opencode.db
```

> ⚠️ Binding to a non-loopback `--host` is insecure (no auth/CSRF).
> Keep it on `127.0.0.1` for local use.



```
opencode-perf-stats [session_id] [options]

Positional:
  session_id              Session ID (default: most recently updated)

Options:
  --version               Show version
  --final-only            Only include finish='stop' messages
  --json                  Output as JSON
  --html [FILE]           Generate interactive HTML report
  --db PATH               Path to opencode.db
  --days N                Filter to last N days (triggers aggregate mode)
  --model SUBSTRING       Filter by model ID (triggers aggregate mode)
  --list                  List recent sessions and exit

Subcommands:
  compare                 Compare sessions, models, or date ranges
  serve                   Launch the web UI (requires the [web] extra)
```

## Database Location

The tool reads from OpenCode's SQLite database:

```
$XDG_DATA_HOME/opencode/opencode.db
# or
~/.local/share/opencode/opencode.db
```

Override with `--db /path/to/opencode.db`.

## Development

```bash
git clone https://github.com/USERNAME/opencode-perf-stats.git
cd opencode-perf-stats
pip install -e ".[web]"

# Run tests
python -m pytest tests/

# Run the tool
opencode-perf-stats --help
```

## License

MIT
