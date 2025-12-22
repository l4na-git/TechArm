"""Logging utilities shared across modules."""

from __future__ import annotations

import logging
import sys
from typing import Optional


def configure_logging(level: int = logging.INFO) -> None:
    """Configure application-wide logging."""
    if logging.getLogger().handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger with default configuration."""
    configure_logging()
    return logging.getLogger(name or "teacharm")
