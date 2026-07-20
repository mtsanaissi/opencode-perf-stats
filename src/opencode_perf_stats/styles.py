"""Shared visual styles for opencode-perf-stats (standalone HTML + web UI).

Single source of truth for the dark-theme CSS palette. Imported by
``reports.html`` (inlined into standalone ``--html`` reports) and copied to
``web/static/styles.css`` for the Flask app.
"""

# ── chart color palette ───────────────────────────────────────────────────────

COLORS = [
    "#4dc9f6", "#f67019", "#f53794", "#537bc4", "#acc236",
    "#166a8f", "#00a950", "#58595b", "#8549ba", "#e6194b",
    "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
]


# ── core dark-theme CSS ───────────────────────────────────────────────────────
# Used by standalone --html reports (inlined) and the web UI (served static).

CSS = """
:root {
    --bg: #1a1a2e;
    --bg-card: #16213e;
    --bg-card-hover: #1a2745;
    --text: #e0e0e0;
    --text-muted: #8892a0;
    --accent: #4dc9f6;
    --accent-dim: rgba(77, 201, 246, 0.15);
    --border: #2a3a5c;
    --green: #acc236;
    --red: #e6194b;
    --orange: #f67019;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
}

h1 {
    font-size: 1.8rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--accent);
}

h2 {
    font-size: 1.3rem;
    font-weight: 600;
    margin-bottom: 1rem;
    color: var(--text);
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.subtitle {
    color: var(--text-muted);
    font-size: 0.9rem;
    margin-bottom: 2rem;
}

.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 1.5rem;
    margin-bottom: 2rem;
}

.card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.5rem;
    transition: background 0.2s;
}

.card:hover { background: var(--bg-card-hover); }

.card-title {
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 0.5rem;
}

.card-value {
    font-size: 2rem;
    font-weight: 700;
    color: var(--text);
}

.card-detail {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin-top: 0.25rem;
}

.chart-container {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}

.chart-container canvas {
    max-height: 350px;
}

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
}

th, td {
    padding: 0.75rem 1rem;
    text-align: left;
    border-bottom: 1px solid var(--border);
}

th {
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
}

tr:hover { background: var(--accent-dim); }

.mono {
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 0.85rem;
}

.badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
}

.badge-green { background: rgba(172, 194, 54, 0.2); color: var(--green); }
.badge-orange { background: rgba(246, 112, 25, 0.2); color: var(--orange); }
.badge-red { background: rgba(230, 25, 75, 0.2); color: var(--red); }
.badge-blue { background: rgba(77, 201, 246, 0.2); color: var(--accent); }
.msg-row-user { background: rgba(77, 201, 246, 0.05); }

/* Modal metadata section (user message context) */
.modal-metadata {
    margin-bottom: 1.5rem;
    padding: 1rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
}
.modal-metadata-title {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 0.75rem;
}
.modal-metadata-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem 1.5rem;
}
.modal-metadata-item {
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
}
.modal-metadata-label {
    font-size: 0.8rem;
    color: var(--text-muted);
    white-space: nowrap;
}
.modal-metadata-value {
    font-size: 0.85rem;
    color: var(--text);
}
.modal-metadata-value.mono {
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 0.8rem;
}

footer {
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--text-muted);
    font-size: 0.8rem;
    text-align: center;
}
"""


# ── web-UI-only CSS (nav, forms, sticky basket) ──────────────────────────────
# Append to CSS for the Flask app; not used by standalone reports.

WEB_CSS = CSS + """

/* ── top navigation ── */
.nav {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
    align-items: center;
    flex-wrap: wrap;
}

.nav-brand {
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--accent);
    margin-right: 1.5rem;
}

.nav a {
    padding: 0.4rem 0.9rem;
    border-radius: 6px;
    color: var(--text-muted);
    font-size: 0.9rem;
    font-weight: 500;
    border: 1px solid transparent;
    transition: all 0.15s;
}

.nav a:hover { background: var(--accent-dim); color: var(--accent); text-decoration: none; }
.nav a.active { background: var(--accent-dim); color: var(--accent); border-color: var(--accent); }

.nav-spacer { flex: 1; }
.nav-meta { color: var(--text-muted); font-size: 0.8rem; }

/* ── forms ── */
.form-row {
    display: flex;
    gap: 0.75rem;
    align-items: flex-end;
    flex-wrap: wrap;
    margin-bottom: 1.5rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.25rem;
}

.form-field { display: flex; flex-direction: column; gap: 0.3rem; }
.form-field label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    font-weight: 600;
}

input[type="text"], input[type="number"], select {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 0.5rem 0.7rem;
    font-size: 0.9rem;
    font-family: inherit;
    min-width: 140px;
}
input:focus, select:focus { outline: none; border-color: var(--accent); }

.btn {
    display: inline-block;
    padding: 0.5rem 1rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-card-hover);
    color: var(--text);
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    text-decoration: none;
    transition: all 0.15s;
    font-family: inherit;
}
.btn:hover { background: var(--accent-dim); color: var(--accent); text-decoration: none; }
.btn-primary { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }
.btn-primary:hover { opacity: 0.9; color: var(--bg); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ── CTA cards on landing ── */
.cta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1.25rem;
    margin-bottom: 2rem;
}
.cta {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.5rem;
    transition: all 0.2s;
    color: var(--text);
}
.cta:hover { border-color: var(--accent); background: var(--bg-card-hover); text-decoration: none; transform: translateY(-2px); }
.cta h3 { color: var(--accent); margin-bottom: 0.4rem; font-size: 1.1rem; }
.cta p { color: var(--text-muted); font-size: 0.88rem; }

/* ── toggle pills ── */
.toggle { display: inline-flex; gap: 0.25rem; }
.toggle a {
    padding: 0.2rem 0.7rem;
    border-radius: 999px;
    font-size: 0.8rem;
    border: 1px solid var(--border);
    color: var(--text-muted);
}
.toggle a.on { background: var(--accent-dim); color: var(--accent); border-color: var(--accent); }

/* ── sticky compare basket ── */
.basket {
    position: sticky;
    bottom: 0;
    left: 0;
    right: 0;
    background: var(--bg-card);
    border-top: 1px solid var(--border);
    padding: 0.85rem 1.25rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin: 2rem -2rem -2rem;
    z-index: 10;
}
.basket-count { font-weight: 600; color: var(--accent); }

/* ── row selection ── */
input[type="checkbox"] { accent-color: var(--accent); width: 1rem; height: 1rem; }
.row-select td { cursor: pointer; }

/* ── error page ── */
.error-box {
    text-align: center;
    padding: 4rem 1rem;
}
.error-code { font-size: 3rem; font-weight: 700; color: var(--accent); }
.error-msg { color: var(--text-muted); margin: 0.5rem 0 1.5rem; }

/* ── empty state ── */
.empty { text-align: center; color: var(--text-muted); padding: 3rem 1rem; }

/* responsive */
@media (max-width: 640px) {
    body { padding: 1rem; }
    .form-row { padding: 1rem; }
    .basket { margin: 2rem -1rem -1rem; }
}
"""
