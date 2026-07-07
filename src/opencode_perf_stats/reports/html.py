"""Self-contained HTML report generator with Chart.js charts."""

import json

from ..styles import CSS, COLORS


# Re-export COLORS for backwards compatibility (other modules import from here).
__all__ = [
    "COLORS",
    "CSS",
    "render_single_html",
    "render_aggregate_html",
    "render_compare_html",
]


# ── single-session HTML ──────────────────────────────────────────────────────

def render_single_html(data: dict) -> str:
    """Render a single-session report as a self-contained HTML page."""
    s = data["session"]
    t = data["tokens"]
    m = data["messages"]
    tps = data["tps"]
    ttft = data["ttft"]

    # Prepare chart data
    tps_labels = [f"#{i+1}" for i in range(len(tps["detail"]))]
    tps_values = [d["tps"] if d["tps"] is not None else 0 for d in tps["detail"]]
    tps_colors = [COLORS[0] if not d["low_confidence"] else "#f67019" for d in tps["detail"]]

    # Build TTFT arrays aligned by message_id
    ttft_map = {x["message_id"]: x for x in ttft["detail"]}
    ttft_chart_labels = []
    ttft_chart_values = []
    for i, d in enumerate(tps["detail"], 1):
        if d["message_id"] in ttft_map:
            ttft_chart_labels.append(f"#{i}")
            ttft_chart_values.append(ttft_map[d["message_id"]]["ttft_ms"])

    token_data = json.dumps({
        "labels": ["Input", "Output", "Reasoning", "Cache Read", "Cache Write"],
        "values": [t["input"], t["output"], t["reasoning"], t["cache_read"], t["cache_write"]],
        "colors": [COLORS[0], COLORS[1], COLORS[2], COLORS[3], COLORS[4]],
    })

    tps_data = json.dumps({
        "labels": tps_labels,
        "values": tps_values,
        "colors": tps_colors,
    })

    ttft_data = json.dumps({
        "labels": ttft_chart_labels,
        "values": ttft_chart_values,
    })

    # Model string
    model_str = f"{s['provider']}/{s['model']}"
    if s["variant"]:
        model_str += f" (variant: {s['variant']})"

    # TPS aggregate
    tps_agg = tps["aggregate"]
    ttft_agg = ttft["aggregate"]

    # Format values for display
    tps_mean_str = f"{tps_agg['mean']:.1f}" if tps_agg['mean'] else "—"
    tps_median_str = f"{tps_agg['median']:.1f}" if tps_agg['median'] else "—"
    tps_min_str = f"{tps_agg['min']:.1f}" if tps_agg['min'] else "—"
    tps_max_str = f"{tps_agg['max']:.1f}" if tps_agg['max'] else "—"
    ttft_mean_str = f"{ttft_agg['mean']:.0f}ms" if ttft_agg['mean'] else "—"
    ttft_median_str = f"{ttft_agg['median']:.0f}ms" if ttft_agg['median'] else "—"
    ttft_min_str = f"{ttft_agg['min']:.0f}ms" if ttft_agg['min'] else "—"
    ttft_max_str = f"{ttft_agg['max']:.0f}ms" if ttft_agg['max'] else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>opencode-perf-stats — {s['title']}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <style>{CSS}</style>
</head>
<body>
    <h1>opencode-perf-stats</h1>
    <p class="subtitle">Session report &mdash; {s['title']}</p>

    <div class="grid">
        <div class="card">
            <div class="card-title">Model</div>
            <div class="card-value" style="font-size:1.2rem">{model_str}</div>
            <div class="card-detail">Agent: {s['agent']}</div>
        </div>
        <div class="card">
            <div class="card-title">Duration</div>
            <div class="card-value" style="font-size:1.5rem">{_fmt_dur_card(s['duration_seconds'])}</div>
            <div class="card-detail">{s['created']}</div>
        </div>
        <div class="card">
            <div class="card-title">Total Cost</div>
            <div class="card-value">${t['cost']:.4f}</div>
            <div class="card-detail">Cache hit: {t['cache_hit_pct']:.1f}%</div>
        </div>
        <div class="card">
            <div class="card-title">Messages</div>
            <div class="card-value">{m['total_assistant']}</div>
            <div class="card-detail">{m['with_timing']} with timing &middot; {m['finish_stop']} final</div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-title">TPS Mean</div>
            <div class="card-value">{tps_mean_str}</div>
            <div class="card-detail">Median: {tps_median_str} &middot; Range: {tps_min_str}–{tps_max_str}</div>
        </div>
        <div class="card">
            <div class="card-title">TTFT Mean</div>
            <div class="card-value">{ttft_mean_str}</div>
            <div class="card-detail">Median: {ttft_median_str} &middot; Range: {ttft_min_str}–{ttft_max_str}</div>
        </div>
        <div class="card">
            <div class="card-title">Tokens</div>
            <div class="card-value" style="font-size:1.3rem">{_fmt_tokens_card(t['input'] + t['output'] + t['reasoning'])}</div>
            <div class="card-detail">In: {_fmt_tokens_card(t['input'])} &middot; Out: {_fmt_tokens_card(t['output'])} &middot; Reason: {_fmt_tokens_card(t['reasoning'])}</div>
        </div>
    </div>

    <div class="chart-container">
        <h2>TPS per Message</h2>
        <canvas id="tpsChart"></canvas>
    </div>

    <div class="chart-container">
        <h2>TTFT per Message (ms)</h2>
        <canvas id="ttftChart"></canvas>
    </div>

    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 1.5rem;">
        <div class="chart-container">
            <h2>Token Breakdown</h2>
            <canvas id="tokenChart"></canvas>
        </div>
        <div class="chart-container">
            <h2>Message Summary</h2>
            <canvas id="msgChart"></canvas>
        </div>
    </div>

    <div class="chart-container">
        <h2>Per-Message Details</h2>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>TPS</th>
                    <th>Output Tokens</th>
                    <th>Duration</th>
                    <th>TTFT</th>
                    <th>Finish</th>
                    <th>Note</th>
                </tr>
            </thead>
            <tbody>
                {_render_detail_rows(data.get("all_messages", tps["detail"]), ttft["detail"])}
            </tbody>
        </table>
    </div>

    <footer>
        Generated by <strong>opencode-perf-stats</strong> &mdash; {s['created']}
    </footer>

    <script>
    const tpsData = {tps_data};
    const ttftData = {ttft_data};
    const tokenData = {token_data};

    Chart.defaults.color = '#8892a0';
    Chart.defaults.borderColor = '#2a3a5c';

    // TPS chart
    new Chart(document.getElementById('tpsChart'), {{
        type: 'bar',
        data: {{
            labels: tpsData.labels,
            datasets: [{{
                label: 'TPS',
                data: tpsData.values,
                backgroundColor: tpsData.colors,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, title: {{ display: true, text: 'Tokens/sec' }} }}
            }}
        }}
    }});

    // TTFT chart
    new Chart(document.getElementById('ttftChart'), {{
        type: 'bar',
        data: {{
            labels: ttftData.labels,
            datasets: [{{
                label: 'TTFT (ms)',
                data: ttftData.values,
                backgroundColor: '#537bc4',
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, title: {{ display: true, text: 'Milliseconds' }} }}
            }}
        }}
    }});

    // Token breakdown doughnut
    new Chart(document.getElementById('tokenChart'), {{
        type: 'doughnut',
        data: {{
            labels: tokenData.labels,
            datasets: [{{
                data: tokenData.values,
                backgroundColor: tokenData.colors,
                borderWidth: 0,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ position: 'bottom' }},
            }}
        }}
    }});

    // Message summary
    new Chart(document.getElementById('msgChart'), {{
        type: 'doughnut',
        data: {{
            labels: ['Final (stop)', 'Tool calls', 'Incomplete'],
            datasets: [{{
                data: [{m['finish_stop']}, {m['finish_tool_calls']}, {m['incomplete']}],
                backgroundColor: ['#acc236', '#f67019', '#58595b'],
                borderWidth: 0,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ position: 'bottom' }},
            }}
        }}
    }});
    </script>
</body>
</html>"""
    return html


def _fmt_dur_card(seconds: float | None) -> str:
    """Format duration for card display."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {s:.0f}s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}h {int(m)}m"


def _fmt_tokens_card(n: int) -> str:
    """Format tokens for card display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _render_detail_rows(tps_detail: list[dict], ttft_detail: list[dict]) -> str:
    """Render HTML table rows for per-message details.

    ``tps_detail`` may be a merged ``all_messages`` list (user + assistant
    entries with a ``role`` key) or the legacy assistant-only ``tps_detail``
    list.  User rows render with "—" for metrics and a "User" badge.
    """
    ttft_map = {d["message_id"]: d for d in ttft_detail}
    rows = []
    for i, d in enumerate(tps_detail, 1):
        if d.get("role") == "user":
            rows.append(
                f"<tr class='msg-row-user'>"
                f"<td>{i}</td><td class='mono'>—</td>"
                f"<td>—</td><td class='mono'>—</td>"
                f"<td class='mono'>—</td>"
                f"<td><span class='badge badge-blue'>User</span></td>"
                f"<td>—</td></tr>"
            )
            continue
        tps_val = f"{d['tps']:.1f}" if d["tps"] is not None else "—"
        dur = _fmt_dur_ms(d["duration_ms"]) if d["duration_ms"] else "—"
        ttft_entry = ttft_map.get(d["message_id"])
        ttft_val = f"{ttft_entry['ttft_ms']:.0f}ms" if ttft_entry else "—"
        note = ""
        if d["low_confidence"]:
            reason = d.get("low_confidence_reason", "low-confidence")
            note = f'<span class="badge badge-orange">{reason}</span>'
        rows.append(
            f"<tr><td>{i}</td><td class='mono'>{tps_val}</td>"
            f"<td>{d['output_tokens']:,}</td><td class='mono'>{dur}</td>"
            f"<td class='mono'>{ttft_val}</td><td>{d['finish']}</td><td>{note}</td></tr>"
        )
    return "\n                ".join(rows)


def _fmt_dur_ms(ms: int) -> str:
    """Format milliseconds as duration."""
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60000:
        return f"{ms/1000:.1f}s"
    return f"{ms/60000:.1f}m"


# ── aggregate HTML ───────────────────────────────────────────────────────────

def render_aggregate_html(data: dict, filter_desc: str) -> str:
    """Render an aggregate report as a self-contained HTML page."""
    ov = data["overview"]
    tk = data["tokens"]
    tps_agg = data["tps"]["aggregate"]
    ttft_agg = data["ttft"]["aggregate"]
    model_rows = data["per_model"]
    top_sessions = data["top_sessions"]

    # Per-model chart data
    model_labels = [r["model"].split("/")[-1][:20] for r in model_rows]
    model_tps_p50 = [r.get("tps_p50") or 0 for r in model_rows]
    model_tps_p95 = [r.get("tps_p95") or 0 for r in model_rows]
    model_ttft_p50 = [r.get("ttft_p50") or 0 for r in model_rows]
    model_ttft_p95 = [r.get("ttft_p95") or 0 for r in model_rows]
    model_output = [r["output_tokens"] for r in model_rows]
    model_costs = [r["cost"] for r in model_rows]

    model_chart_data = json.dumps({
        "labels": model_labels,
        "tps_p50": model_tps_p50,
        "tps_p95": model_tps_p95,
        "ttft_p50": model_ttft_p50,
        "ttft_p95": model_ttft_p95,
        "output": model_output,
        "costs": model_costs,
    })

    # Top sessions chart
    top_labels = [s["title"][:25] for s in top_sessions]
    top_output = [s["output_tokens"] for s in top_sessions]
    top_chart_data = json.dumps({
        "labels": top_labels,
        "output": top_output,
    })

    # Format values for display (UI shows p50 headline + p95 detail).
    tps_p50_str = f"{tps_agg['median']:.1f}" if tps_agg.get('median') is not None else "—"
    tps_p95_str = f"{tps_agg['p95']:.1f}{' ⚠' if tps_agg.get('low_n') and tps_agg.get('p95') is not None else ''}" if tps_agg.get('p95') is not None else "—"
    ttft_p50_str = f"{ttft_agg['median']:.0f}ms" if ttft_agg.get('median') is not None else "—"
    ttft_p95_str = f"{ttft_agg['p95']:.0f}ms{' ⚠' if ttft_agg.get('low_n') and ttft_agg.get('p95') is not None else ''}" if ttft_agg.get('p95') is not None else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>opencode-perf-stats — Aggregate Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <style>{CSS}</style>
</head>
<body>
    <h1>opencode-perf-stats</h1>
    <p class="subtitle">Aggregate report &mdash; {filter_desc} &mdash; {ov['session_count']} sessions, {ov['message_count']} messages</p>

    <div class="grid">
        <div class="card">
            <div class="card-title">Sessions</div>
            <div class="card-value">{ov['session_count']}</div>
            <div class="card-detail">{ov['message_count']} messages</div>
        </div>
        <div class="card">
            <div class="card-title">Total Cost</div>
            <div class="card-value">${tk['cost']:.4f}</div>
            <div class="card-detail">Cache hit: {tk['cache_hit_pct']:.1f}%</div>
        </div>
        <div class="card">
            <div class="card-title">TPS p50</div>
            <div class="card-value">{tps_p50_str}</div>
            <div class="card-detail">p95: {tps_p95_str}</div>
        </div>
        <div class="card">
            <div class="card-title">TTFT p50</div>
            <div class="card-value">{ttft_p50_str}</div>
            <div class="card-detail">p95: {ttft_p95_str}</div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-title">Input Tokens</div>
            <div class="card-value">{_fmt_tokens_card(tk['input'])}</div>
        </div>
        <div class="card">
            <div class="card-title">Output Tokens</div>
            <div class="card-value">{_fmt_tokens_card(tk['output'])}</div>
        </div>
        <div class="card">
            <div class="card-title">Cache Read</div>
            <div class="card-value">{_fmt_tokens_card(tk['cache_read'])}</div>
        </div>
    </div>

    <div class="chart-container">
        <h2>Per-Model TPS</h2>
        <canvas id="modelTpsChart"></canvas>
    </div>

    <div class="chart-container">
        <h2>Per-Model TTFT</h2>
        <canvas id="modelTtftChart"></canvas>
    </div>

    <div class="chart-container">
        <h2>Per-Model Output Tokens</h2>
        <canvas id="modelOutputChart"></canvas>
    </div>

    <div class="chart-container">
        <h2>Top Sessions by Output Tokens</h2>
        <canvas id="topSessionsChart"></canvas>
    </div>

    <div class="chart-container">
        <h2>Per-Model Breakdown</h2>
        <table>
            <thead>
                <tr>
                    <th>Model</th>
                    <th>Messages</th>
                    <th>Output Tokens</th>
                    <th>TPS p50</th>
                    <th>TPS p95</th>
                    <th>TTFT p50</th>
                    <th>TTFT p95</th>
                    <th>Cost</th>
                </tr>
            </thead>
            <tbody>
                {_render_model_rows(model_rows)}
            </tbody>
        </table>
    </div>

    <div class="chart-container">
        <h2>Top Sessions</h2>
        <table>
            <thead>
                <tr>
                    <th>Session</th>
                    <th>Title</th>
                    <th>Model</th>
                    <th>Output</th>
                    <th>Cost</th>
                    <th>Duration</th>
                </tr>
            </thead>
            <tbody>
                {_render_session_rows(top_sessions)}
            </tbody>
        </table>
    </div>

    <footer>
        Generated by <strong>opencode-perf-stats</strong>
    </footer>

    <script>
    const modelData = {model_chart_data};
    const topData = {top_chart_data};

    Chart.defaults.color = '#8892a0';
    Chart.defaults.borderColor = '#2a3a5c';

    // Per-model TPS
    new Chart(document.getElementById('modelTpsChart'), {{
        type: 'bar',
        data: {{
            labels: modelData.labels,
            datasets: [
                {{
                    label: 'TPS p50',
                    data: modelData.tps_p50,
                    backgroundColor: '#4dc9f6',
                    borderRadius: 4,
                }},
                {{
                    label: 'TPS p95',
                    data: modelData.tps_p95,
                    backgroundColor: '#537bc4',
                    borderRadius: 4,
                }}
            ]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ position: 'top' }} }},
            scales: {{
                y: {{ beginAtZero: true, title: {{ display: true, text: 'Tokens/sec' }} }}
            }}
        }}
    }});

    // Per-model TTFT
    new Chart(document.getElementById('modelTtftChart'), {{
        type: 'bar',
        data: {{
            labels: modelData.labels,
            datasets: [
                {{
                    label: 'TTFT p50 (ms)',
                    data: modelData.ttft_p50,
                    backgroundColor: '#4dc9f6',
                    borderRadius: 4,
                }},
                {{
                    label: 'TTFT p95 (ms)',
                    data: modelData.ttft_p95,
                    backgroundColor: '#537bc4',
                    borderRadius: 4,
                }}
            ]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ position: 'top' }} }},
            scales: {{
                y: {{ beginAtZero: true, title: {{ display: true, text: 'ms' }} }}
            }}
        }}
    }});

    // Per-model output tokens
    new Chart(document.getElementById('modelOutputChart'), {{
        type: 'bar',
        data: {{
            labels: modelData.labels,
            datasets: [{{
                label: 'Output Tokens',
                data: modelData.output,
                backgroundColor: '#acc236',
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, title: {{ display: true, text: 'Tokens' }} }}
            }}
        }}
    }});

    // Top sessions
    new Chart(document.getElementById('topSessionsChart'), {{
        type: 'bar',
        data: {{
            labels: topData.labels,
            datasets: [{{
                label: 'Output Tokens',
                data: topData.output,
                backgroundColor: '#f67019',
                borderRadius: 4,
            }}]
        }},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ beginAtZero: true, title: {{ display: true, text: 'Tokens' }} }}
            }}
        }}
    }});
    </script>
</body>
</html>"""
    return html


def _render_model_rows(model_rows: list[dict]) -> str:
    """Render HTML table rows for per-model breakdown."""
    rows = []
    for r in model_rows:
        tps_p50 = f"{r['tps_p50']:.1f}" if r.get("tps_p50") is not None else "—"
        tps_p95 = f"{r['tps_p95']:.1f}" + (" ⚠" if r.get("tps_low_n") else "") if r.get("tps_p95") is not None else "—"
        ttft_p50 = f"{r['ttft_p50']:.0f}ms" if r.get("ttft_p50") is not None else "—"
        ttft_p95 = f"{r['ttft_p95']:.0f}ms" + (" ⚠" if r.get("ttft_low_n") else "") if r.get("ttft_p95") is not None else "—"
        rows.append(
            f"<tr><td class='mono'>{r['model']}</td><td>{r['messages']:,}</td>"
            f"<td>{r['output_tokens']:,}</td><td class='mono'>{tps_p50}</td>"
            f"<td class='mono'>{tps_p95}</td><td class='mono'>{ttft_p50}</td>"
            f"<td class='mono'>{ttft_p95}</td><td>${r['cost']:.4f}</td></tr>"
        )
    return "\n                ".join(rows)


def _render_session_rows(top_sessions: list[dict]) -> str:
    """Render HTML table rows for top sessions."""
    rows = []
    for s in top_sessions:
        dur = _fmt_dur_card(s["duration_seconds"]) if s["duration_seconds"] else "—"
        rows.append(
            f"<tr><td class='mono'>{s['id'][:20]}</td><td>{s['title']}</td>"
            f"<td class='mono'>{s['model']}</td><td>{s['output_tokens']:,}</td>"
            f"<td>${s['cost']:.4f}</td><td>{dur}</td></tr>"
        )
    return "\n                ".join(rows)


# ── comparison HTML ──────────────────────────────────────────────────────────

def render_compare_html(comparison: dict) -> str:
    """Render a comparison (sessions/models) as a self-contained HTML page.

    Consumes the locked comparison dict schema from ``compare.py``:
    ``{"type", "count", "items": [{"label", "metrics": {...}}, ...]}``.
    """
    ctype = comparison["type"]
    items = comparison["items"]
    count = comparison["count"]

    labels = [i["label"] for i in items]
    tps_means = [i["metrics"]["tps_mean"] or 0 for i in items]
    ttft_means = [i["metrics"]["ttft_mean"] or 0 for i in items]
    tokens_totals = [i["metrics"]["tokens_total"] for i in items]
    costs = [i["metrics"]["cost"] for i in items]
    costs_per_million = [
        i["metrics"]["cost"] / i["metrics"]["tokens_total"] * 1_000_000
        if i["metrics"]["tokens_total"] else 0
        for i in items
    ]

    colors = [COLORS[i % len(COLORS)] for i in range(len(items))]

    chart_data = json.dumps({
        "labels": labels,
        "colors": colors,
        "tps_means": tps_means,
        "ttft_means": ttft_means,
        "tokens_totals": tokens_totals,
        "costs": costs,
        "costs_per_million": costs_per_million,
    })

    title = {"sessions": "Session Comparison",
             "models": "Model Comparison"}.get(ctype, "Comparison")

    # Extra identity row per type.
    if ctype == "sessions":
        extra_header = "Model"
        extra_values = [i.get("model", "—") for i in items]
    else:  # models
        extra_header = "Sessions"
        extra_values = [str(i.get("session_count", "—")) for i in items]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>opencode-perf-stats — {title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <style>{CSS}</style>
</head>
<body>
    <h1>opencode-perf-stats</h1>
    <p class="subtitle">{title} &mdash; {count} item(s)</p>

    <div class="chart-container">
        <h2>TPS Mean</h2>
        <canvas id="tpsChart"></canvas>
    </div>

    <div class="chart-container">
        <h2>TTFT Mean (ms)</h2>
        <canvas id="ttftChart"></canvas>
    </div>

    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 1.5rem;">
        <div class="chart-container">
            <h2>Total Tokens</h2>
            <canvas id="tokensChart"></canvas>
        </div>
        <div class="chart-container">
            <h2>Cost</h2>
            <canvas id="costChart"></canvas>
        </div>
    </div>

    <div class="chart-container">
        <h2>Side-by-side Comparison</h2>
        <table>
            <thead>
                <tr>
                    <th>Metric</th>
                    <th>{extra_header}</th>
                    {''.join(f'<th>{l}</th>' for l in labels)}
                </tr>
            </thead>
            <tbody>
                {_render_compare_rows(items, extra_values)}
            </tbody>
        </table>
    </div>

    <footer>
        Generated by <strong>opencode-perf-stats</strong>
    </footer>

    <script>
    const cmpData = {chart_data};

    Chart.defaults.color = '#8892a0';
    Chart.defaults.borderColor = '#2a3a5c';

    new Chart(document.getElementById('tpsChart'), {{
        type: 'bar',
        data: {{
            labels: cmpData.labels,
            datasets: [{{ label: 'TPS Mean', data: cmpData.tps_means, backgroundColor: cmpData.colors, borderRadius: 4 }}]
        }},
        options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'Tokens/sec' }} }} }} }}
    }});

    new Chart(document.getElementById('ttftChart'), {{
        type: 'bar',
        data: {{
            labels: cmpData.labels,
            datasets: [{{ label: 'TTFT Mean (ms)', data: cmpData.ttft_means, backgroundColor: cmpData.colors, borderRadius: 4 }}]
        }},
        options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'Milliseconds' }} }} }} }}
    }});

    new Chart(document.getElementById('tokensChart'), {{
        type: 'bar',
        data: {{
            labels: cmpData.labels,
            datasets: [{{ label: 'Total Tokens', data: cmpData.tokens_totals, backgroundColor: cmpData.colors, borderRadius: 4 }}]
        }},
        options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'Tokens' }} }} }} }}
    }});

    new Chart(document.getElementById('costChart'), {{
        type: 'bar',
        data: {{
            labels: cmpData.labels,
            datasets: [
                {{ label: 'Total Cost', data: cmpData.costs, backgroundColor: '#4dc9f6', borderRadius: 4 }},
                {{ label: 'Cost per 1M Tokens', data: cmpData.costs_per_million, backgroundColor: '#f67019', borderRadius: 4 }},
            ]
        }},
        options: {{ responsive: true, plugins: {{ legend: {{ position: 'top' }} }}, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'USD' }} }} }} }}
    }});
    </script>
</body>
</html>"""
    return html


def _render_compare_rows(items: list[dict], extra_values: list[str]) -> str:
    """Render the side-by-side comparison table body from the locked metrics schema."""
    rows = []
    # Identity extra column.
    for mkey, label in [
        ("tps_mean", "TPS Mean"),
        ("tps_median", "TPS Median"),
        ("ttft_mean", "TTFT Mean"),
        ("ttft_median", "TTFT Median"),
        ("tokens_input", "Input Tokens"),
        ("tokens_output", "Output Tokens"),
        ("tokens_reasoning", "Reasoning Tokens"),
        ("tokens_total", "Total Tokens"),
        ("cost", "Cost"),
        ("message_count", "Messages"),
        ("duration_seconds", "Duration"),
        ("finish_stop", "Final (stop)"),
        ("finish_tool_calls", "Tool calls"),
    ]:
        cells = [_fmt_cmp_metric(i["metrics"], mkey) for i in items]
        extra_cell = extra_values[0] if mkey == "tps_mean" else _extra_for_key(mkey, extra_values)
        rows.append(
            f"<tr><td>{label}</td><td class='mono'>{extra_cell}</td>"
            + "".join(f"<td class='mono'>{c}</td>" for c in cells)
            + "</tr>"
        )
    return "\n                ".join(rows)


def _extra_for_key(mkey: str, extra_values: list[str]) -> str:
    """Only the first metric row shows the extra (identity) column value."""
    return extra_values[0] if mkey == "tps_mean" else ""


def _fmt_cmp_metric(metrics: dict, key: str) -> str:
    """Format a comparison metric cell."""
    v = metrics.get(key)
    if v is None or v == 0 and key in ("finish_stop", "finish_tool_calls"):
        if key in ("finish_stop", "finish_tool_calls"):
            return str(v) if v else "—"
        return "—"
    if v is None:
        return "—"
    if key in ("tps_mean", "tps_median"):
        return f"{v:.1f}"
    if key in ("ttft_mean", "ttft_median"):
        return f"{v:.0f}ms"
    if key == "cost":
        return f"${v:.4f}"
    if key == "duration_seconds":
        return _fmt_dur_card(v) if v else "—"
    if key in ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_total", "message_count"):
        return f"{v:,}"
    return str(v)
