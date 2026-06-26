"""Flask web UI for opencode-perf-stats.

Provides a ``serve`` subcommand launching a localhost dev server exposing all
four modes (discovery, single-session, aggregate, comparison) through a modern,
intuitive UI. Requires the ``web`` optional dependency (``flask``).
"""

from .app import create_app

__all__ = ["create_app"]
