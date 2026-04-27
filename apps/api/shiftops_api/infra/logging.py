"""Structured logging configuration.

Centralised so we never call `print()` in the codebase. Outputs JSON in
production, pretty-printed locally.
"""

from __future__ import annotations

import logging
import sys

import structlog

from shiftops_api.config import get_settings


def _add_logger_name_compat(
    logger: object, _method_name: str, event_dict: dict
) -> dict:
    """stdlib.add_logger_name assumes logging.Logger; PrintLogger has no .name (Fly/prod)."""
    name = getattr(logger, "name", None)
    if isinstance(name, str) and name:
        event_dict["logger"] = name
    else:
        event_dict["logger"] = "shiftops"
    return event_dict


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _add_logger_name_compat,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.app_env == "local":
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout, force=True)
