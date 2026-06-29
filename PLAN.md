# Web UI Implementation Plan

Performance analytics for OpenCode sessions, delivered through a modern, intuitive web UI.

---

## 1. Requirements

### 1.1 Goal

Provide a full-featured web UI for `opencode-perf-stats` covering every mode the CLI currently exposes — session discovery, single-session reports, aggregate reports, and comparison (sessions/models/days) — with a modern, simple, intuitive UX.

### 1.2 Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | **Discovery view** (`/`): list recent sessions (id, title, agent, model, output tokens, cost, updated), filterable by `days` and `model` substring. |
| FR-2 | **Single-session view** (`/session/<id>`): render TPS, TTFT, token/cost breakdown, message summary, per-message detail table; toggle for `final_only` (finish='stop'). |
| FR-3 | **Aggregate view** (`/aggregate`): aggregate TPS/TTFT/tokens across sessions matching `days`/`model`/`final_only` filters; per-model breakdown table + top sessions. |
| FR-4 | **Comparison view** (`/compare`): compare 2–4 sessions side by side; compare models. Render shared comparison table + grouped charts. (Date-range comparison was removed in favour of the time-series Trends view.) |
| FR-4b | **Trends view** (`/trends`): time-series analysis bucketing metrics by day/week/month/year (shared period selector), with stacked per-model charts for TPS, TTFT, tokens, cost, sessions, and messages. Each chart is independently toggleable. Defaults to the last 30 days. |
| FR-5 | **Selection basket**: on discovery, checkbox-select sessions and trigger comparison for the selected set (2–4). |
| FR-6 | **CTA buttons**: each mode reachable via explicit call-to-action buttons/tabs (Discover / Aggregate / Trends / Compare). |
| FR-7 | **Charts**: Chart.js bar/doughnut charts reused from existing `reports/html.py` (TPS per message, TTFT per message, token doughnut, message doughnut, per-model grouped bars, top sessions). |
| FR-8 | **DB override**: `--db PATH` honored throughout the UI (no multi-tenant state). |
| FR-9 | **`serve` subcommand**: `opencode-perf-stats serve [--port] [--host] [--db] [--no-browser]` launches a localhost dev server and opens the browser. |

### 1.3 Non-Functional Requirements

- **Stack**: Flask + Jinja2 + Chart.js. No JavaScript build step, no node toolchain. Small vanilla JS only.
- **Reuse**: existing dark-theme CSS palette, `db.py` query layer, `build_report_data` / `build_aggregate_data` data builders. No data-access duplication.
- **Read-only**: SQLite opened read-only per request (matches CLI behavior); single-process dev server is acceptable for a local tool.
- **Packaging**: Flask stays an optional dependency (`[web]` extra). `serve` requires the extra; other CLI behavior unchanged.
- **Backward compatibility**: CLI commands (`--list`, `--days`, `--json`, `--html`, `compare`) behavior unchanged after refactor.
- **Security**: `serve` binds to `127.0.0.1` by default; non-loopback binding documented as insecure (no CSRF/auth for localhost).

### 1.4 Out of Scope

- Authentication / multi-user / remote deployment (localhost-only).
- Offline vendoring of Chart.js (CDN acceptable, matches existing standalone reports).
- Pagination beyond the existing 20-row discovery cap.
- WebSocket/live updates.

---

## 2. Codebase Context (discovery summary)

| Module | Role | Reuse for UI |
|---|---|---|
| `db.py` | All SQLite queries + `connect()`/`resolve_db_path()`/`build_session_filter()` | Direct reuse, per-request connection |
| `formatting.py` | `fmt_ts`, `fmt_duration`, `fmt_tokens`, `aggregate` | Direct reuse (both templates and standalone HTML) |
| `reports/markdown.py` | `build_report_data`, `build_aggregate_data` (pure data dicts) | Direct reuse — already JSON-serializable |
| `reports/html.py` | Standalone Chart.js HTML reports + `CSS` dark-theme constant | Extract CSS; reuse palette/chart patterns |
| `compare.py` | Sessions/models/days comparison; **HTML comparison is a JSON-only stub** | Refactor into pure builders; implement real HTML |
| `cli.py` | argparse dispatch + `compare` early-dispatch pattern | Add `serve` subcommand mirroring `compare` pattern |

**Key signals:**
- `pyproject.toml` declares `web = ["flask>=3.0"]` but no Flask app exists yet — web UI was anticipated.
- `reports/html.py` already contains a polished dark CSS palette, Chart.js integration, and card/chart/table components.
- Comparison HTML path (`compare.py:_write_compare_stub`) only dumps JSON — completing it is part of "full functionality."
- Data dicts are already JSON-serializable (`default=str`) — convenient for Jinja's `|tojson`.

**Inferred `opencode.db` schema** (from SQL in `db.py`):
- `session` table: `id, title, agent, model (JSON), cost, tokens_input/output/reasoning, tokens_cache_read/write, time_created, time_updated, time_compacting, metadata (JSON)`.
- `message` table: `id, session_id, time_created, data (JSON with $.role, $.time.created/completed, $.tokens.*, $.finish, $.modelID, $.providerID, $.cost)`.
- `part` table: `message_id, data (JSON with $.time.start, $.type)`.
- Confirm against a real `opencode.db` when seeding test fixtures.

---

## 3. Execution Plan

### Step 1 — Create web app package
**Path:** `src/opencode_perf_stats/web/`

New package:
- `__init__.py` — `create_app(db_path: str) -> Flask` factory. Stores `db_path` on `app.config`.
- `app.py` — Flask app + all routes. Each route opens a short-lived `db.connect()`/`close()` per request (matches CLI's per-invocation pattern; SQLite read-only; 3s busy timeout already set in `db.connect`).
- `templates/` — `base.html`, `discovery.html`, `single.html`, `aggregate.html`, `compare.html`, partials.
- `static/` — `app.js` (selection basket), `styles.css` (extracted from existing CSS constant).

### Step 2 — Extract shared CSS into a shared module (no circular dep)
**Path:** `src/opencode_perf_stats/styles.py` (shared module) + `src/opencode_perf_stats/web/static/styles.css` (served copy)

Extract the `CSS` constant into a shared module `opencode_perf_stats/styles.py` (a plain `CSS: str` constant). This avoids the circular dependency that would arise if `reports/html.py` imported from `web/` (web → reports for builders; reports → web for CSS would be circular):
- `reports/html.py` imports `CSS` from `opencode_perf_stats.styles` and inlines it into standalone `--html` reports (keeps them self-contained).
- `web/static/styles.css` is a copy of the same string, served via `url_for('static', filename='styles.css')` for the Flask app.
- A single source of truth (the `styles.py` constant); a build step is **not** required — `web/__init__.py` can write the static file via `importlib.resources` on first import, or the static file is generated once and committed. Preserves dark theme, card grid, table, badge components.

### Step 3 — Define route surface
**Path:** `src/opencode_perf_stats/web/app.py`

**DB connection lifecycle:** use Flask's `g` object + `@app.teardown_appcontext`. A `get_db()` helper returns `g._db` (lazily opened via `db.connect(app.config["DB_PATH"])`); the teardown closes it if present. This matches the CLI's per-invocation connection model and SQLite read-only + 3s busy timeout.

**Error handling per route:**
- Session not found → `404` (render `error.html` with message), **not** `sys.exit(1)`.
- Invalid params (e.g., `<4` sessions to compare, non-integer `days`) → `400` with message.
- Database errors / unexpected → `500` with a generic message (detail logged to stderr).

**Discovery query:** do **not** reuse `cmd_list()` (it prints directly). Instead add a new `fetch_discovery_sessions(conn, where, params)` to `db.py` (Step 3.1) returning the raw list of dicts that `cmd_list`'s JSON branch already builds internally. Refactor `cmd_list` to call it so CLI and web share one query.

All GET, form-driven where filters apply:

| Route | Purpose | Data builders called |
|---|---|---|
| `GET /` | Discovery (filter form + session table) | `build_session_filter` + `fetch_discovery_sessions` |
| `GET /session/<id>?final_only=1` | Single-session report | `fetch_session` + `fetch_assistant_messages` + `fetch_ttft` + `build_report_data` |
| `GET /aggregate?days=N&model=...&final_only=1` | Aggregate report | `build_session_filter` + `fetch_matching_sessions` + `fetch_aggregate_messages` + `fetch_aggregate_ttft` + `build_aggregate_data` |
| `GET /trends?days=N&model=...&period=day&final_only=1` | Time-series trends (day/week/month/year) | `build_session_filter` + `build_time_series` (reuses `fetch_matching_sessions` + `fetch_aggregate_messages` + `fetch_aggregate_ttft` + `formatting.aggregate`) |
| `GET /compare/sessions?ids=ses_a,ses_b,...` | Session comparison (2–4) | `build_sessions_comparison` |
| `GET /compare/models?names=mimo,gpt-4,...` | Model comparison (≥2) | `build_models_comparison` |

Selection basket on discovery persists selected IDs in the URL query string so "Compare selected (N)" links straight to `/compare/sessions?ids=...`.

**Flask config:** `SECRET_KEY` set (os.urandom-based, stable per process), `DEBUG=False`, stderr logging. Template context always includes `DB_PATH` and nav state.

**Step 3.1 — Add `fetch_discovery_sessions()` to `db.py`:**
```python
def fetch_discovery_sessions(conn, where: str, params: list, limit: int = 20) -> list[dict]:
    """Return recent sessions for discovery (shared by CLI --list and web /)."""
    # Same SELECT currently inside cmd_list(), returning the list of dicts
    # that the JSON branch of cmd_list already constructs.
```

### Step 4 — Refactor `compare.py` to expose pure data builders
**Path:** `src/opencode_perf_stats/compare.py`

Extract bodies of `_compare_sessions` / `_compare_models` / `_compare_days` into pure functions taking `sqlite3.Connection` + plain params, returning the comparison dict:

- `build_sessions_comparison(conn, session_ids: list[str]) -> dict`
- `build_models_comparison(conn, model_names: list[str]) -> dict`
- `build_days_comparison(conn, day_ints: list[int]) -> dict`

Each returns `{"type": ..., "count": ..., ...}` — same shape `run_compare` already constructs. Removes the `FakeArgs` hack by accepting explicit `days`/`model` params. `run_compare` (CLI) becomes a thin wrapper calling these builders then dispatching JSON/Markdown/HTML output. Flask `compare` route calls the same builders. **Lock the dict schema here before writing the template in Step 5.**

**Comparison dict schemas (locked):**

```python
# build_sessions_comparison -> {"type": "sessions", "count": N, "items": [ {...}, ... ]}
{
  "type": "sessions",
  "count": N,
  "items": [
    {
      "label": <title>,        # comparison column label
      "id": <session_id>,
      "model": <"provider/model">,
      "metrics": {
        "tps_mean": <float|null>,
        "tps_median": <float|null>,
        "ttft_mean": <float|null>,   # ms
        "ttft_median": <float|null>,
        "tokens_input": <int>,
        "tokens_output": <int>,
        "tokens_reasoning": <int>,
        "tokens_total": <int>,
        "cost": <float>,
        "duration_seconds": <float|null>,
        "message_count": <int>,
        "finish_stop": <int>,
        "finish_tool_calls": <int>,
      }
    }, ...
  ]
}

# build_models_comparison -> {"type": "models", "count": N, "items": [ {...}, ... ]}
{
  "type": "models",
  "count": N,
  "items": [
    {
      "label": <model_name>,
      "model": <"provider/model">,
      "session_count": <int>,
      "metrics": { tps_mean, tps_median, ttft_mean, ttft_median,
                   tokens_input, tokens_output, tokens_reasoning, tokens_total,
                   cost, message_count }   # no duration_seconds (aggregate)
    }, ...
  ]
}

# build_days_comparison -> {"type": "days", "count": N, "items": [ {...}, ... ]}
{
  "type": "days",
  "count": N,
  "items": [
    {
      "label": "Last <N> days",
      "days": <int>,
      "session_count": <int>,
      "metrics": { tps_mean, tps_median, ttft_mean, ttft_median,
                   tokens_input, tokens_output, tokens_reasoning, tokens_total,
                   cost, message_count }
    }, ...
  ]
}
```

`metrics` is the same set of keys across all three types where applicable; the template renders a side-by-side table keyed on `metrics` and labeled by `label`. This supersedes the ad-hoc shapes (`sessions`/`models`/`periods`) currently in `compare.py` — the CLI `_print_*_comparison` helpers are updated to read from `items[][*].metrics` so JSON/Markdown output remains equivalent.

### Step 5 — Implement comparison HTML rendering (CLI + web)
**Paths:** `src/opencode_perf_stats/reports/html.py`, `templates/compare.html`

Replace `_write_compare_stub` with real `render_compare_html(comparison: dict) -> str`:
- Standalone full-page HTML (doctype + head + Chart.js CDN + existing CSS).
- Mirrors structure of `render_single_html` / `render_aggregate_html`.
- Charts: grouped bar for TPS mean across items, grouped bar for TTFT mean across items, side-by-side comparison table (reusing `_render_model_rows` / `_render_session_rows` helpers).
- Handles all three `type` values (`sessions`, `models`, `days`) by branching on dict shape.

Jinja `compare.html` consumes the same dict, renders table + charts inline within `base.html`.

### Step 6 — Wire `serve` subcommand into CLI
**Path:** `src/opencode_perf_stats/cli.py`

Mirror existing `compare` early-dispatch: in `main()`, if `sys.argv[1] == "serve"`, call new `_handle_serve_command()` parsing:
- `--port` (default 5000)
- `--host` (default 127.0.0.1; warn to stderr if non-loopback)
- `--db PATH`
- `--no-browser` (disables auto-open; specialist named `--no-open` — same intent, keep `--no-browser` for consistency with naming elsewhere)

Then `create_app(db_path)`, fallback to `resolve_db_path()` if `--db` absent. `app.run(host, port, debug=False)`. Auto-open browser via `webbrowser.open` unless `--no-browser`. Catch `OSError` on port-in-use → print actionable message ("port 5000 in use; try --port 5001") and exit non-zero. Add `serve` to CLI help epilog and README.

### Step 7 — Build templates
**Path:** `src/opencode_perf_stats/web/templates/`

**Template inheritance pattern:** all page templates `{% extends "base.html" %}` and override `{% block content %}`. `{% block title %}` sets the `<title>`. Context passed via Flask's `render_template(template, **ctx, nav=active_tab)` — `base.html` renders the nav based on `nav`.

- `base.html`: shared layout, top nav (tabs: Discover | Aggregate | Compare), dark-theme styles via `styles.css`, Chart.js CDN in `<head>`, `{% block content %}`.
- `error.html`: extends `base.html`, renders `error_code` + `error_message` (used by 404/400/500 handlers).
- `discovery.html`: filter `<form method="get">` (days, model, submit), results table from discovery query, each row → link to `/session/<id>` + checkbox bound to compare basket. Sticky footer "Compare selected (N)" → `/compare/sessions?ids=...`. Honors existing 20-row cap.
- `single.html`: cards (Model, Duration, Cost, Messages, TPS, TTFT, Tokens) + Chart.js canvases + per-message detail table. `final_only` toggle via `?final_only=1` / `0`.
- `aggregate.html`: filter form (days, model, final_only) + overview cards + per-model grouped bars + top-sessions table.
- `compare.html`: selector form (type radio: sessions/models/days + multi-select/inputs) + comparison table (keyed on `items[*].metrics`) + grouped bar charts.

All templates inject data via Jinja `|tojson` (matches existing `json.dumps` injection in standalone reports). Static files served by Flask's dev server in development; no production WSGI concerns (out of scope per §1.4).

### Step 8 — Static JS for selection basket
**Path:** `src/opencode_perf_stats/web/static/app.js`

Vanilla JS:
- Track checked session rows on discovery.
- Update sticky "Compare selected (N)" button `href`.
- Persist selection in `sessionStorage` (survives navigation).

No framework, no build step. Chart.js init stays inline in templates (matches existing pattern).

### Step 9 — Add smoke tests for web app
**Path:** `tests/test_web.py`

Using Flask test client on `create_app(db_path)` with a minimal seeded temp SQLite DB (schema inferred from `db.py`; confirm against real `opencode.db`):
- `GET /` → 200, contains nav.
- `GET /session/<id>` → 200, contains session title.
- `GET /aggregate?days=7` → 200.
- `GET /compare?ids=ses_a,ses_b` → 200 (validates 2-item minimum).
- `create_app` importable; `serve` listed in CLI `--help`.

### Step 10 — Update packaging and docs
**Paths:** `pyproject.toml`, `README.md`

- Keep `flask>=3.0` in `web` extra (already present). Document `pip install -e ".[web]"` required for `serve`.
- Add **Web UI** section to README: `opencode-perf-stats serve [--port 5000] [--host 127.0.0.1] [--db PATH] [--no-browser]` + short description of four modes.
- Update CLI Reference to list `serve` alongside `compare`.

---

## 4. Assumptions

- Single-process Flask dev server adequate for local analytics (no concurrent users).
- Per-request `db.connect()`/`close()` fine for SQLite read-only (CLI already opens one per invocation with 3s busy timeout).
- Chart.js via CDN acceptable (existing standalone reports already do this); no offline vendoring.
- Existing `build_report_data` / `build_aggregate_data` / `aggregate` reused as-is — already pure, JSON-serializable.
- New comparison builders return same dict shape currently produced inline by `compare.py` → CLI `compare` JSON/Markdown output stays byte-compatible.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| **DB schema coupling in tests** — `tests/test_smoke.py` has no SQLite fixture; testing web routes E2E requires a seeded temp DB or mocking `db.connect`. Plan prefers minimal seeded temp DB; schema inferred from `db.py` queries — **confirm against real `opencode.db` during implementation.** | Seed temp DB from inferred schema; validate against real DB before merging. |
| **Markup duplication** between standalone `--html` (`reports/html.py`) and Jinja templates. | Shared CSS via Step 2; accept markup divergence (different delivery contexts). Flag for future unification. |
| **Comparison dict stability** — web routes depend on refactored builders returning exactly the keys `compare.html` expects. | Lock dict schema in Step 4 before writing template in Step 5. |
| **Selection basket edge cases** — URL length limits if many IDs selected (capped at 4 → low risk). `sessionStorage` may surprise users expecting server-side state. | Acceptable for local tool; document as client-side. |
| **`serve` to non-loopback** — no auth/CSRF on localhost dev server. | Default `--host 127.0.0.1`; flag insecurity in `serve --help` for non-loopback. |

---

## 6. Unknowns

- **Exact `opencode.db` schema** — inferred from `db.py` SQL (see §2). Confirm against real DB when seeding test fixtures.
- **Whether `pip install -e ".[web]"` should become default** — deferred. `[web]` stays optional; users opt in only for `serve`.
- **CSRF / auth** — unnecessary for localhost dev server; becomes real concern if `--host 0.0.0.0` used.

---

## 7. Validation

- [ ] `python -m pytest tests/` passes including new `tests/test_web.py`.
- [ ] `opencode-perf-stats serve` launches browser at `http://127.0.0.1:5000/` showing discovery table.
- [ ] Clicking a session row loads single-session report with charts.
- [ ] Aggregate filter form returns filtered results with charts.
- [ ] Selecting 2–4 sessions + "Compare selected" renders comparison table + grouped charts.
- [ ] `opencode-perf-stats compare sessions ses_a ses_b --html out.html` produces a real standalone HTML comparison report (not JSON stub) — verified by opening `out.html`.
- [ ] `opencode-perf-stats --help` lists `serve` alongside `compare`; `opencode-perf-stats serve --help` shows `--port`, `--host`, `--db`, `--no-browser`.
- [ ] Existing CLI behavior unchanged after `compare.py` refactor — `tests/test_smoke.py` re-run green.
