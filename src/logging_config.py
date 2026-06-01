"""
Logging setup — one place that configures the root logger format and level.

Call `get_logger(__name__)` from any module to get a properly configured
logger. Configuration is idempotent, so importing this from many modules is
safe.
"""

from __future__ import annotations

import logging

from src.config import settings

_CONFIGURED = False

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def _configure_root() -> None:
    """Configure the root logger exactly once for the process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format=_LOG_FORMAT)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given module name."""
    _configure_root()
    return logging.getLogger(name)
