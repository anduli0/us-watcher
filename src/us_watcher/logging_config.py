"""Structured logging setup (structlog). JSON in prod, console locally.

Sensitive values must never be logged; secrets are :class:`SecretStr` and are
not passed to log calls. This module only configures formatting/levels.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from us_watcher.config import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if settings.log_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "us_watcher") -> Any:
    configure_logging()
    return structlog.get_logger(name)
