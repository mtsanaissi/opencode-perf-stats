"""Formatting helpers for display."""

import statistics
from datetime import datetime, timezone


def fmt_ts(ms: int | None) -> str:
    """Format a millisecond timestamp as a human-readable UTC string."""
    if ms is None:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_duration(seconds: float | None) -> str:
    """Format seconds as a human-readable duration string."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {s:.0f}s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}h {int(m)}m {s:.0f}s"


def fmt_tokens(n: int) -> str:
    """Format a token count with K/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (NumPy-default method) on a pre-sorted list."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return float(sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo]))


# Below this sample size, tail percentiles (p95) are noisy and flagged as low-confidence.
LOW_N_THRESHOLD = 20


def aggregate(values: list[float]) -> dict:
    """Compute aggregate stats (count, mean, median, p95, min, max).

    ``mean``/``median`` are kept for JSON/API backward compatibility; the UI
    surfaces ``median`` (p50) + ``p95`` as the latency-representative pair, since
    TPS/TTFT distributions are right-skewed. ``low_n`` flags sparse samples
    (< LOW_N_THRESHOLD) where p95 is unreliable.
    """
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None,
                "min": None, "max": None, "low_n": False}
    s = sorted(values)
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "p95": _percentile(s, 95),
        "min": s[0],
        "max": s[-1],
        "low_n": len(values) < LOW_N_THRESHOLD,
    }
