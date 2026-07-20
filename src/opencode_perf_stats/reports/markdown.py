"""Markdown and JSON report generation."""

import json
import sqlite3
import statistics

from ..formatting import fmt_ts, fmt_duration, fmt_tokens, aggregate


# ── single-session report ─────────────────────────────────────────────────────

def build_report_data(
    session: dict,
    messages: list[dict],
    ttft_map: dict[str, dict],
    final_only: bool,
    user_messages: list[dict] | None = None,
) -> dict:
    """Assemble the full single-session report dict (JSON or Markdown).

    ``user_messages`` (optional) is a list of ``{"id", "created"}`` dicts
    from ``fetch_user_messages``.  When provided, a merged ``all_messages``
    list is built — user and assistant entries interleaved chronologically —
    for the Per-Message Details table.  The ``tps.detail`` and ``ttft.detail``
    lists remain assistant-only (charts depend on them).
    """

    total_assistant = len(messages)
    timed = [m for m in messages if m["has_timing"]]
    incomplete = [m for m in messages if not m["has_timing"]]
    tool_calls = [m for m in messages if m["finish"] == "tool-calls"]
    stops = [m for m in messages if m["finish"] == "stop"]

    if final_only:
        stat_messages = [m for m in timed if m["finish"] == "stop"]
        filter_label = "final answers only (finish='stop')"
    else:
        stat_messages = timed
        filter_label = "all assistant messages with timing"

    tps_values = [m["tps"] for m in stat_messages if m["tps"] is not None]
    ttft_values = [ttft_map[m["id"]]["ttft_ms"] for m in stat_messages if m["id"] in ttft_map]

    tps_detail = []
    for m in stat_messages:
        tps_detail.append({
            "message_id": m["id"],
            "tps": round(m["tps"], 1) if m["tps"] is not None else None,
            "output_tokens": m["output_tokens"],
            "duration_ms": m["duration_ms"],
            "finish": m["finish"],
            "low_confidence": m["low_confidence"],
            "low_confidence_reason": m["low_confidence_reason"],
            # Extra fields for expandable row detail.
            "input_tokens": m["input_tokens"],
            "reasoning_tokens": m["reasoning_tokens"],
            "cache_read": m["cache_read"],
            "cache_write": m["cache_write"],
            "cost": round(m["cost"], 4),
            "created_ms": m["created"],
            "completed_ms": m["completed"],
            "model_id": m["model_id"],
            "provider_id": m["provider_id"],
        })

    ttft_detail = []
    for m in stat_messages:
        if m["id"] in ttft_map:
            entry = ttft_map[m["id"]]
            ttft_detail.append({
                "message_id": m["id"],
                "ttft_ms": entry["ttft_ms"],
                "first_token_type": entry["part_type"],
                "output_tokens": m["output_tokens"],
                "finish": m["finish"],
            })

    # Build a merged list of user + assistant messages for the Per-Message
    # Details table.  User messages always appear (not affected by final_only);
    # assistant entries inherit the final_only filter from tps_detail.
    all_messages = []
    for um in (user_messages or []):
        all_messages.append({
            "role": "user",
            "message_id": um["id"],
            "tps": None,
            "output_tokens": 0,
            "duration_ms": None,
            "finish": None,
            "low_confidence": False,
            "low_confidence_reason": None,
            "input_tokens": 0,
            "reasoning_tokens": 0,
            "cache_read": 0,
            "cache_write": 0,
            "cost": 0.0,
            "created_ms": um["created"],
            "completed_ms": None,
            # Metadata from message.data (not available on assistant messages).
            "agent": um.get("agent"),
            "model_id": um.get("model_id"),
            "provider_id": um.get("provider_id"),
            "variant": um.get("variant"),
        })
    for d in tps_detail:
        all_messages.append({"role": "assistant", **d})
    # Sort by (created_ms, role_priority) — user before assistant on ties.
    all_messages.sort(key=lambda x: (x["created_ms"] or 0, 0 if x["role"] == "user" else 1))

    duration_s = None
    if session["time_created"] and session["time_updated"]:
        duration_s = (session["time_updated"] - session["time_created"]) / 1000

    return {
        "session": {
            "id": session["id"],
            "title": session["title"],
            "agent": session["agent"],
            "model": session["model"],
            "provider": session["provider"],
            "variant": session["variant"],
            "created": fmt_ts(session["time_created"]),
            "updated": fmt_ts(session["time_updated"]),
            "duration_seconds": round(duration_s, 1) if duration_s is not None else None,
            "time_compacting": fmt_ts(session["time_compacting"]) if session["time_compacting"] else None,
            "metadata": session["metadata"] if session["metadata"] else None,
        },
        "tokens": {
            "input": session["tokens_input"],
            "output": session["tokens_output"],
            "reasoning": session["tokens_reasoning"],
            "cache_read": session["tokens_cache_read"],
            "cache_write": session["tokens_cache_write"],
            "cache_hit_pct": round((session["tokens_cache_read"] / (session["tokens_input"] + session["tokens_cache_read"])) * 100, 1) if (session["tokens_input"] + session["tokens_cache_read"]) > 0 else 0.0,
            "cost": round(session["cost"], 4),
        },
        "messages": {
            "total_assistant": total_assistant,
            "with_timing": len(timed),
            "incomplete": len(incomplete),
            "finish_stop": len(stops),
            "finish_tool_calls": len(tool_calls),
            "filter": filter_label,
        },
        "tps": {
            "detail": tps_detail,
            "aggregate": aggregate(tps_values),
        },
        "ttft": {
            "detail": ttft_detail,
            "aggregate": aggregate(ttft_values),
        },
        "all_messages": all_messages,
    }


def render_markdown(data: dict) -> str:
    """Render the single-session report as Markdown."""
    s = data["session"]
    t = data["tokens"]
    m = data["messages"]
    tps = data["tps"]
    ttft = data["ttft"]

    lines = []

    lines.append("## Session")
    lines.append(f"- **ID**: `{s['id']}`")
    lines.append(f"- **Title**: {s['title']}")
    lines.append(f"- **Agent**: {s['agent']}")
    model_str = f"{s['provider']}/{s['model']}"
    if s["variant"]:
        model_str += f" (variant: {s['variant']})"
    lines.append(f"- **Model**: {model_str}")
    lines.append(f"- **Created**: {s['created']}")
    lines.append(f"- **Updated**: {s['updated']}")
    lines.append(f"- **Wall-clock duration**: {fmt_duration(s['duration_seconds'])}")
    if s["time_compacting"]:
        lines.append(f"- **Last compacted**: {s['time_compacting']}")
    lines.append("")

    lines.append("## Tokens & Cost")
    lines.append(f"- **Input**: {fmt_tokens(t['input'])} ({t['input']:,})")
    lines.append(f"- **Output**: {fmt_tokens(t['output'])} ({t['output']:,})")
    lines.append(f"- **Reasoning**: {fmt_tokens(t['reasoning'])} ({t['reasoning']:,})")
    cache_read_pct = (t['cache_read'] / (t['input'] + t['cache_read'])) * 100 if (t['input'] + t['cache_read']) > 0 else 0.0
    lines.append(f"- **Cache read**: {fmt_tokens(t['cache_read'])} ({cache_read_pct:.1f}%)")
    lines.append(f"- **Cache write**: {fmt_tokens(t['cache_write'])} ({t['cache_write']:,})")
    lines.append(f"- **Cost**: ${t['cost']:.4f}")
    lines.append("")

    lines.append("## Messages")
    lines.append(f"- **Total assistant**: {m['total_assistant']}")
    lines.append(f"- **With timing data**: {m['with_timing']}")
    lines.append(f"- **Incomplete (no timing)**: {m['incomplete']}")
    lines.append(f"- **finish='stop'**: {m['finish_stop']}")
    lines.append(f"- **finish='tool-calls'**: {m['finish_tool_calls']}")
    lines.append(f"- **Filter applied**: {m['filter']}")
    lines.append("")

    # ── TPS ──
    agg = tps["aggregate"]
    lines.append("## TPS (tokens per second)")
    if agg["count"] == 0:
        lines.append("(no messages with timing data for this filter)")
    else:
        lines.append(f"- **Count**: {agg['count']}")
        lines.append(f"- **Mean**: {agg['mean']:.1f}")
        lines.append(f"- **Median**: {agg['median']:.1f}")
        lines.append(f"- **Min**: {agg['min']:.1f}")
        lines.append(f"- **Max**: {agg['max']:.1f}")
        lines.append("")
        lines.append("### Per-message")
        lines.append("| # | Role | TPS | Output tokens | Duration | Finish | Note |")
        lines.append("|---|------|-----|---------------|----------|--------|------|")
        for i, d in enumerate(data.get("all_messages", tps["detail"]), 1):
            role = d.get("role", "assistant")
            if role == "user":
                lines.append(f"| {i} | user | — | — | — | — | — |")
                continue
            note = ""
            if d["low_confidence"]:
                note = f"⚠ {d['low_confidence_reason']}" if d["low_confidence_reason"] else "⚠ low-confidence"
            dur = fmt_duration(d["duration_ms"] / 1000) if d["duration_ms"] else "—"
            lines.append(
                f"| {i} | assistant | {d['tps']:.1f} | {d['output_tokens']:,} | {dur} | {d['finish']} | {note} |"
            )
    lines.append("")

    # ── TTFT ──
    agg = ttft["aggregate"]
    lines.append("## TTFT (time to first token, ms)")
    lines.append("_First part with `time.start`, any type (text or reasoning)._")
    if agg["count"] == 0:
        lines.append("(no messages with first-token timing for this filter)")
    else:
        lines.append(f"- **Count**: {agg['count']}")
        lines.append(f"- **Mean**: {agg['mean']:.0f}ms ({agg['mean']/1000:.2f}s)")
        lines.append(f"- **Median**: {agg['median']:.0f}ms ({agg['median']/1000:.2f}s)")
        lines.append(f"- **Min**: {agg['min']:.0f}ms ({agg['min']/1000:.2f}s)")
        lines.append(f"- **Max**: {agg['max']:.0f}ms ({agg['max']/1000:.2f}s)")
        lines.append("")
        lines.append("### Per-message")
        lines.append("| # | TTFT | | First part | Output tokens | Finish |")
        lines.append("|---|------|-|------------|---------------|--------|")
        for i, d in enumerate(ttft["detail"], 1):
            ttft_s = d["ttft_ms"] / 1000
            lines.append(
                f"| {i} | {d['ttft_ms']:.0f}ms | ({ttft_s:.2f}s) | {d['first_token_type']} | {d['output_tokens']:,} | {d['finish']} |"
            )
    lines.append("")

    if data["messages"]["incomplete"] > 0 and not data["messages"]["filter"].startswith("final"):
        lines.append(f"_Note: {data['messages']['incomplete']} assistant message(s) lacked "
                     f"completed timing and were excluded from TPS/TTFT stats._")
        lines.append("")

    return "\n".join(lines)


# ── --list mode ───────────────────────────────────────────────────────────────

def cmd_list(conn: sqlite3.Connection, where: str, params: list, json_out: bool) -> None:
    """Print recent sessions for discovery, then exit."""
    from ..db import fetch_discovery_sessions

    rows = fetch_discovery_sessions(conn, where, params, limit=20)

    if json_out:
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "title": r["title"],
                "agent": r["agent"],
                "model": r["model"],
                "provider": r["provider"],
                "tokens_output": r["tokens_output"],
                "tokens_input": r["tokens_input"],
                "cost": r["cost"],
                "created": r["created"],
                "updated": r["updated"],
            })
        print(json.dumps(out, indent=2))
        return

    if not rows:
        print("(no sessions match)")
        return

    print(f"{'Session ID':<32} {'Title':<28} {'Agent':<8} {'Model':<22} {'Output':>8} {'Cost':>8} Updated")
    print("-" * 128)
    for r in rows:
        model = r["model"][:22]
        title = r["title"][:28]
        out = fmt_tokens(r["tokens_output"])
        cost = f"${r['cost']:.2f}"
        updated = r["updated"][5:22] if r["updated"] != "—" else "—"
        print(f"{r['id']:<32} {title:<28} {r['agent'][:8]:<8} {model:<22} {out:>8} {cost:>8} {updated}")


# ── aggregate mode ───────────────────────────────────────────────────────────

def build_aggregate_data(
    sessions: list[dict],
    messages: list[dict],
    ttft_rows: list[dict],
    final_only: bool,
) -> dict:
    """Build the aggregate data dict (shared by Markdown, JSON, and HTML)."""

    # Apply --final-only to message-level TPS (TTFT already filtered in SQL).
    if final_only:
        msgs_for_stats = [m for m in messages if m["finish"] == "stop"]
    else:
        msgs_for_stats = messages

    tps_values = [m["tps"] for m in msgs_for_stats if m["tps"] is not None and not m["low_confidence"]]
    ttft_values = [t["ttft_ms"] for t in ttft_rows]

    # Per-model aggregation.
    by_model: dict[str, list[dict]] = {}
    for m in msgs_for_stats:
        key = f"{m['provider_id']}/{m['model_id']}"
        by_model.setdefault(key, []).append(m)

    # ttft_rows carry only message_id (no model); index for per-model grouping.
    ttft_by_msg = {t["message_id"]: t["ttft_ms"] for t in ttft_rows}

    model_rows = []
    for key, msgs in sorted(by_model.items(), key=lambda kv: -sum(x["output_tokens"] for x in kv[1])):
        tps_vals = [x["tps"] for x in msgs if x["tps"] is not None and not x["low_confidence"]]
        model_ttft = [ttft_by_msg[x["id"]] for x in msgs if x["id"] in ttft_by_msg]
        tps_stats = aggregate(tps_vals)
        ttft_stats = aggregate(model_ttft)
        model_rows.append({
            "model": key,
            "messages": len(msgs),
            "output_tokens": sum(x["output_tokens"] for x in msgs),
            # JSON backward-compat (kept; UI hides these for latency metrics).
            "tps_mean": round(tps_stats["mean"], 1) if tps_stats["mean"] is not None else None,
            "tps_median": round(tps_stats["median"], 1) if tps_stats["median"] is not None else None,
            # UI-facing latency pair (p50/p95).
            "tps_p50": round(tps_stats["median"], 1) if tps_stats["median"] is not None else None,
            "tps_p95": round(tps_stats["p95"], 1) if tps_stats["p95"] is not None else None,
            "tps_low_n": tps_stats["low_n"],
            "ttft_mean": round(ttft_stats["mean"]) if ttft_stats["mean"] is not None else None,
            "ttft_median": round(ttft_stats["median"]) if ttft_stats["median"] is not None else None,
            "ttft_p50": round(ttft_stats["median"]) if ttft_stats["median"] is not None else None,
            "ttft_p95": round(ttft_stats["p95"]) if ttft_stats["p95"] is not None else None,
            "ttft_low_n": ttft_stats["low_n"],
            "cost": round(sum(x["cost"] for x in msgs), 4),
        })

    # Top sessions by output tokens (cap 10).
    top_sessions = []
    for s in sorted(sessions, key=lambda x: -x["tokens_output"])[:10]:
        dur = (s["time_updated"] - s["time_created"]) / 1000 if s["time_updated"] and s["time_created"] else None
        top_sessions.append({
            "id": s["id"],
            "title": s["title"][:40],
            "model": f"{s['provider']}/{s['model']}",
            "output_tokens": s["tokens_output"],
            "cost": round(s["cost"], 4),
            "duration_seconds": round(dur, 1) if dur else None,
        })

    total_out = sum(s["tokens_output"] for s in sessions)
    total_in = sum(s["tokens_input"] for s in sessions)
    total_cache = sum(s["tokens_cache_read"] for s in sessions)
    total_cost = sum(s["cost"] for s in sessions)

    return {
        "overview": {
            "session_count": len(sessions),
            "message_count": len(messages),
            "filter": "final answers only (finish='stop')" if final_only else "all assistant messages with timing",
        },
        "tokens": {
            "input": total_in,
            "output": total_out,
            "cache_read": total_cache,
            "cache_hit_pct": round((total_cache / (total_in + total_cache)) * 100, 1) if (total_in + total_cache) > 0 else 0.0,
            "cost": round(total_cost, 4),
        },
        "tps": {
            "aggregate": aggregate(tps_values),
            "note": "excludes low-confidence messages (short duration or low token count)",
        },
        "ttft": {
            "aggregate": aggregate(ttft_values),
        },
        "per_model": model_rows,
        "top_sessions": top_sessions,
    }


def render_aggregate_markdown(data: dict) -> str:
    """Render aggregate data as Markdown."""
    lines = []

    ov = data["overview"]
    tk = data["tokens"]
    lines.append("## Aggregate overview")
    lines.append(f"- **Sessions**: {ov['session_count']}")
    lines.append(f"- **Messages**: {ov['message_count']}")
    lines.append(f"- **Filter**: {ov['filter']}")
    lines.append(f"- **Input**: {fmt_tokens(tk['input'])} ({tk['input']:,})")
    lines.append(f"- **Output**: {fmt_tokens(tk['output'])} ({tk['output']:,})")
    cache_read_pct = (tk['cache_read'] / (tk['input'] + tk['cache_read'])) * 100 if (tk['input'] + tk['cache_read']) > 0 else 0.0
    lines.append(f"- **Cache read**: {fmt_tokens(tk['cache_read'])} ({cache_read_pct:.1f}%)")
    lines.append(f"- **Cost**: ${tk['cost']:.4f}")
    lines.append("")

    tps_agg = data["tps"]["aggregate"]
    lines.append("## TPS (excluding low-confidence)")
    if tps_agg["count"]:
        lines.append(f"- **Count**: {tps_agg['count']}")
        lines.append(f"- **Mean**: {tps_agg['mean']:.1f}")
        lines.append(f"- **Median**: {tps_agg['median']:.1f}")
        lines.append(f"- **Min**: {tps_agg['min']:.1f}")
        lines.append(f"- **Max**: {tps_agg['max']:.1f}")
    else:
        lines.append("(no messages)")
    lines.append("")

    ttft_agg = data["ttft"]["aggregate"]
    lines.append("## TTFT (time to first token, ms)")
    if ttft_agg["count"]:
        lines.append(f"- **Count**: {ttft_agg['count']}")
        lines.append(f"- **Mean**: {ttft_agg['mean']:.0f}ms ({ttft_agg['mean']/1000:.2f}s)")
        lines.append(f"- **Median**: {ttft_agg['median']:.0f}ms ({ttft_agg['median']/1000:.2f}s)")
        lines.append(f"- **Min**: {ttft_agg['min']:.0f}ms ({ttft_agg['min']/1000:.2f}s)")
        lines.append(f"- **Max**: {ttft_agg['max']:.0f}ms ({ttft_agg['max']/1000:.2f}s)")
    else:
        lines.append("(no messages)")
    lines.append("")

    model_rows = data["per_model"]
    lines.append("## Per-model breakdown")
    lines.append("| Model | Messages | Output tokens | TPS p50 | TPS p95 | TTFT p50 | TTFT p95 | Cost |")
    lines.append("|-------|----------|---------------|---------|---------|----------|----------|------|")
    for r in model_rows:
        tps_p50 = f"{r['tps_p50']:.1f}" if r["tps_p50"] is not None else "—"
        tps_p95 = f"{r['tps_p95']:.1f}" + (" ⚠" if r.get("tps_low_n") else "") if r["tps_p95"] is not None else "—"
        ttft_p50 = f"{r['ttft_p50']:.0f}ms" if r["ttft_p50"] is not None else "—"
        ttft_p95 = f"{r['ttft_p95']:.0f}ms" + (" ⚠" if r.get("ttft_low_n") else "") if r["ttft_p95"] is not None else "—"
        lines.append(f"| {r['model']} | {r['messages']:,} | {r['output_tokens']:,} | {tps_p50} | {tps_p95} | {ttft_p50} | {ttft_p95} | ${r['cost']:.4f} |")
    lines.append("")

    top_sessions = data["top_sessions"]
    lines.append("## Top sessions (by output tokens)")
    lines.append("| Session ID | Title | Model | Output | Cost | Duration |")
    lines.append("|------------|-------|-------|--------|------|----------|")
    for s in top_sessions:
        dur = fmt_duration(s["duration_seconds"]) if s["duration_seconds"] else "—"
        lines.append(f"| `{s['id'][:24]}` | {s['title']} | {s['model']} | {s['output_tokens']:,} | ${s['cost']:.4f} | {dur} |")

    return "\n".join(lines)


def cmd_aggregate(
    conn: sqlite3.Connection,
    sessions: list[dict],
    messages: list[dict],
    ttft_rows: list[dict],
    final_only: bool,
    json_out: bool,
) -> None:
    """Aggregate TPS/TTFT/tokens across many sessions.

    `messages` and `ttft_rows` are pre-filtered for --final-only by the SQL
    queries in fetch_aggregate_*; no per-row finish lookup needed here.
    """
    data = build_aggregate_data(sessions, messages, ttft_rows, final_only)

    if json_out:
        print(json.dumps(data, indent=2, default=str))
        return

    print(render_aggregate_markdown(data))
