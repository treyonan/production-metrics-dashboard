"""structlog-backed structured JSON logging.

``configure_logging()`` is called once from the app lifespan. After
that, any module can ``from app.core.logging import get_logger`` and
emit structured logs that include the current correlation ID.

We do not currently route uvicorn / stdlib logs through structlog — a
deliberate scope limit. Adding a ``ProcessorFormatter`` bridge is a
small follow-up when we want uvicorn access logs as JSON.
"""

import logging
from typing import Any

import structlog

from app.core.correlation import correlation_id_var


def _add_correlation_id(
    _logger: object, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor — stamps the current correlation ID on every event."""
    cid = correlation_id_var.get()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON output, filtered at ``level``."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
