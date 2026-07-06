"""Central logging setup.

One consistent format for the whole app. Modules get a logger with
`logging.getLogger(__name__)` — never `print()` — so output carries a
timestamp, level, and the module it came from, and can be filtered by level.
"""

import logging

from src.core.config import get_settings

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    """Configure the root logger. Called once at application startup."""
    logging.basicConfig(level=get_settings().log_level.upper(), format=_FORMAT)
    # Quiet down noisy third-party loggers; our own logs stay at the chosen level.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
