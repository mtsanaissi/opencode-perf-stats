"""Performance analytics for OpenCode sessions."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("opencode-perf-stats")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0+unknown"
