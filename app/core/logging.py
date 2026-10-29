"""Structured JSON logging. `request_id` / `user_id` are bound per request through contextvars."""

import logging
import sys

import structlog

MAX_TEXT_LOG_CHARS = 200


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def truncate(text: str, limit: int = MAX_TEXT_LOG_CHARS) -> str:
    """Keep user-supplied text (e.g. hypotheses) short in logs."""
    return text if len(text) <= limit else text[:limit] + "…"
