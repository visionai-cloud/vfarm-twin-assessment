"""Minimal structured-ish logging setup.

One place to configure the root logger. In production you'd swap the formatter
for JSON and ship to your log pipeline; the call sites (logger.info/…) stay the
same.
"""
from __future__ import annotations

import logging

from .config import settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
