# opencode-perf-stats

[![PyPI version](https://img.shields.io/pypi/v/opencode-perf-stats.svg)](https://pypi.org/project/opencode-perf-stats/)
[![Python](https://img.shields.io/pypi/pyversions/opencode-perf-stats.svg)](https://pypi.org/project/opencode-perf-stats/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Performance analytics for [OpenCode](https://opencode.ai) sessions — TPS, TTFT, tokens, cost, and comparisons, with an interactive web UI.

## Key Features

- **Interactive web UI** — discover, aggregate, trend, and compare in the browser
- **CLI available** — analyze sessions straight from the terminal
- **Self-contained HTML reports** — shareable Chart.js charts, no server needed
- **Model-aware aggregation** — per-model p50/p95 breakdowns
- **Low-confidence filtering** — noisy short messages auto-excluded from stats

## Demo

<!-- TODO: Record a GIF of navigating the Web UI and place it as demo.gif in the repo root.
     Suggested flow: Discover → click a session → Aggregate → Trends → Compare.
     Tools: asciinema + agg, vhs, or a screen recorder; export as demo.gif. -->

![opencode-perf-stats Web UI demo](demo.gif)

## Table of Contents

- [Key Features](#key-features)
- [Demo](#demo)
- [Install](#install)
- [Quick Start](#quick-start)
- [Web UI](#web-ui)
- [Modes](#modes)
- [HTML Reports](#html-reports)
- [How Metrics Are Calculated](#how-metrics-are-calculated)
- [CLI Reference](#cli-reference)
- [Database Location](#database-location)
- [Roadmap](#roadmap)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Install

```bash
# Recommended (includes the web UI)
pip install "opencode-perf-stats[web]"
```

Or with [pipx](https://pypa.github.io/pipx/) (recommended for CLI tools):

```bash
pipx install "opencode-perf-stats[web]"
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uvx opencode-perf-stats --help
```

> ⚠️ `uvx` runs the CLI in an isolated environment without the `[web]` extra,
> so `opencode-perf-stats serve` will fail with an `ImportError` for Flask.
> To use the web UI, install with `pip` or `pipx` as shown above.

CLI-only install (no web UI):

```bash
pip install opencode-perf-stats
```

## Quick Start

```bash
# Launch the interactive web UI (recommended)
opencode-perf-stats serve

# …or analyze from the terminal:
opencode-perf-stats                  # most recent session
opencode-perf-stats --days 7         # aggregate, last 7 days
opencode-perf-stats --list           # list recent sessions
```

## Web UI

An interactive browser UI covers every mode with modern, intuitive UX:
session discovery, single-session reports, aggregate views, per-period time
analysis, and side-by-side comparison. Requires the optional `web` extra:

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
- **Trends (`/trends`)** — time-series analysis: bucket metrics by day, week,
  month, or year (shared period selector), with stacked per-model charts for
  TPS, TTFT, tokens, cost, sessions, and messages. Each chart is independently
  toggleable. Defaults to the last 30 days.
- **Compare (`/compare`)** — compare sessions or models side-by-side with
  grouped bar charts and a comparison table.
- **Single session (`/session/<id>`)** — full report with TPS/TTFT/token
  charts and a per-message detail table; `final_only` toggle.

```bash
opencode-perf-stats serve --port 5001      # custom port
opencode-perf-stats serve --no-browser     # don't auto-open a browser
opencode-perf-stats serve --db /path/to/opencode.db
```

> ⚠️ Binding to a non-loopback `--host` is insecure (no auth/CSRF).
> Keep it on `127.0.0.1` for local use.

## Modes

| Mode | Description | Trigger |
|------|-------------|---------|
| **Single-Session** | Per-message TPS, TTFT, tokens, cost | Default / `ses_<id>` |
| **Aggregate** | Cross-session stats, per-model breakdown | `--days N` / `--model` |
| **Discovery** | List recent sessions | `--list` |
| **Comparison** | Side-by-side sessions or models | `compare` subcommand |

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

Compare sessions or models side by side.

```bash
# Compare up to 4 sessions
opencode-perf-stats compare sessions ses_a ses_b ses_c ses_d

# Compare models
opencode-perf-stats compare models mimo gpt-4 claude

# JSON output
opencode-perf-stats compare sessions ses_a ses_b --json
```

## HTML Reports

Generate self-contained HTML reports with interactive Chart.js charts:

```bash
# Save a single-session report to a file
opencode-perf-stats --html report.html

# Aggregate report filtered by days
opencode-perf-stats --days 7 --html report.html

# Pipe HTML to stdout (bare --html and --html - are equivalent)
opencode-perf-stats --html > report.html
opencode-perf-stats --html - | head -n 20
```

Charts include:
- **TPS per message** — bar chart with low-confidence markers
- **TTFT per message** — time to first token visualization
- **Token breakdown** — doughnut chart (input/output/reasoning/cache)
- **Message summary** — final vs tool-calls vs incomplete
- **Per-model comparison** — grouped bars (aggregate mode)
- **Top sessions** — horizontal bar chart (aggregate mode)

## How Metrics Are Calculated

All metrics are derived from the timing and token data OpenCode records in its
SQLite database. This tool reads that data — it does not time requests itself.

### TPS (Tokens Per Second)

- Measured **per assistant message**.
- Formula: `output tokens / generation duration`.
- Generation duration = time between when the message was created and when it
  completed (both recorded by OpenCode).
- Only output tokens are counted — input, reasoning, and cache tokens are
  excluded.

### TTFT (Time To First Token)

- Measured **per assistant message**, in milliseconds.
- The time from when the message was created to when the **first streaming part**
  (text or reasoning) started.
- Considers all part types, so messages that only contain tool calls still get a
  TTFT via their reasoning part.

### Cost

- Read directly from OpenCode's database — **this tool does not compute pricing**.
- Per-message cost and per-session cost are summed for aggregates and per-model
  breakdowns.

### Low-confidence filtering

- Messages with very few output tokens (< 20) or very short durations (< 1 s)
  produce noisy TPS values and are flagged as **low-confidence**.
- In aggregate views, low-confidence messages are **excluded** from TPS stats.
- When fewer than 20 samples are available, p95 values are flagged as unreliable.

### Aggregation

- TPS and TTFT are reported as **mean, median (p50), p95, min, and max**.
- p95 uses linear-interpolation percentile (the NumPy-default method).
- Per-model breakdowns group messages by `provider/model` identity.

## CLI Reference

```
opencode-perf-stats [session_id] [options]

Positional:
  session_id              Session ID (default: most recently updated)

Options:
  --version               Show version
  --final-only            Only include finish='stop' messages
  --json                  Output as JSON
  --html [FILE]           Generate interactive HTML report;
                          writes to FILE, or stdout when FILE is
                          omitted or '-'
  --db PATH               Path to opencode.db
  --days N                Filter to last N days (triggers aggregate mode)
  --model SUBSTRING       Filter by model ID (triggers aggregate mode)
  --list                  List recent sessions and exit

Subcommands:
  compare                 Compare sessions or models
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

## Roadmap

These features are planned for upcoming releases:

- **Web UI color customization** — let users switch the dark-theme palette
  (chart colors, accent, background) via config or environment variables.
- **Budget tracking** — define per-model prices and monthly/weekly budgets.
  The tool will warn when a session or period exceeds the configured threshold
  and show remaining budget in aggregate views.
- **More analytics splits** — group metrics by *message type* (`stop` vs
  `tool-calls`) and by *individual tool name*, so you can see which tools or
  message categories are the most expensive or the slowest.

## Development

```bash
git clone https://github.com/mtsanaissi/opencode-perf-stats.git
cd opencode-perf-stats
pip install -e ".[web]"

# Run tests
python -m pytest tests/

# Run the tool
opencode-perf-stats --help
```

## Contributing

Contributions are welcome! Here's how to get started:

1. Fork the repository and create a feature branch.
2. Install development dependencies: `pip install -e ".[web]"`
3. Make your changes and add tests if applicable.
4. Run the test suite: `python -m pytest tests/`
5. Open a pull request against `main`.

For bugs and feature requests, please [open an issue](https://github.com/mtsanaissi/opencode-perf-stats/issues).

## License

MIT
