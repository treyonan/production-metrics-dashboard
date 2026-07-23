"""FastAPI dependency providers.

Every dependency lives here so route handlers stay thin.

Phase 13 (2026-04-28): SQL is the only production-report source. The
provider grabs the pool from ``app.state`` (populated in main.py's
lifespan) and hands it to ``SqlProductionReportSource``.

Why no ``lru_cache``: the provider needs the per-request ``Request``
to reach ``request.app.state.sql_pool``. The source itself is cheap to
construct per request (just a pool reference), so dropping the cache
costs nothing meaningful.

Test contexts inject a different source via ``app.dependency_overrides``
on the route's dependency -- see ``tests/conftest.py``.
"""

from __future__ import annotations

import time

from fastapi import HTTPException, Request

from app.core.logging import get_logger
from app.integrations.production_report.base import ProductionReportSource
from app.integrations.production_report.labels import (
    LABEL_CACHE_TTL_SECONDS,
    ChartLabels,
)
from app.integrations.production_report.sql_source import SqlProductionReportSource

_log = get_logger("app.api.dependencies")


def get_production_report_source(request: Request) -> ProductionReportSource:
    """Return the SQL production-report source.

    Returns 503 when the SQL pool failed to initialize (bad
    ``DB_CONN_STRING``, network issue at startup, etc.) -- the API
    stays up so /api/health can surface the unhealthy source rather
    than the whole process refusing requests.
    """
    pool = getattr(request.app.state, "sql_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "SQL source unavailable: pool not initialized. "
                "Check uvicorn startup log for 'sql_pool.create_failed' "
                "or 'sql_pool.not_created'."
            ),
        )
    return SqlProductionReportSource(pool=pool)


def get_configured_run_report_source(request: Request):
    """Return the Configured Run Report source (Phase 31).

    Same pool-from-``app.state`` pattern as
    ``get_production_report_source``; returns 503 when the SQL pool
    didn't initialize so /api/health can surface it.
    """
    from app.integrations.production_report.configured_run_report import (
        ConfiguredRunReportSource,
    )

    pool = getattr(request.app.state, "sql_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Configured-run-report source unavailable: SQL pool not "
                "initialized. Check uvicorn startup log for "
                "'sql_pool.create_failed' or 'sql_pool.not_created'."
            ),
        )
    return ConfiguredRunReportSource(pool=pool)


def get_dio_source(request: Request):
    """Return the DIO / Days-of-Supply source (Spec 005).

    Same pool-from-``app.state`` pattern as
    ``get_configured_run_report_source``; returns 503 when the SQL pool
    didn't initialize so /api/health can surface it.
    """
    from app.integrations.dio.source import DioSource

    pool = getattr(request.app.state, "sql_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "DIO source unavailable: SQL pool not initialized. "
                "Check uvicorn startup log for 'sql_pool.create_failed' "
                "or 'sql_pool.not_created'."
            ),
        )
    return DioSource(pool=pool)


def get_interval_metric_source(request: Request):
    """Return the configured interval-metric source.

    Today only one implementation: ``SqlIntervalMetricSource`` reading
    from ``[FLOW].[INTERVAL_METRIC_TAGS]`` and fanning out to Flow's
    REST API. Returns 503 from this provider when either dependency
    is missing -- the SQL pool (lifespan-created when the SQL backend
    is selected) or the FlowClient (lifespan-created when at least
    one of ``PMD_FLOW_API_KEY`` or any per-site
    ``PMD_FLOW_API_KEY_<site_id>`` is set in env).
    """
    from app.integrations.metrics.sql_source import SqlIntervalMetricSource

    pool = getattr(request.app.state, "sql_pool", None)
    flow_client = getattr(request.app.state, "flow_client", None)

    missing = []
    if pool is None:
        missing.append("sql_pool")
    if flow_client is None:
        missing.append("flow_client")
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "Interval-metric source unavailable: "
                + ", ".join(missing)
                + " not initialized. Check uvicorn startup log for "
                "sql_pool.create_failed / flow_client.not_created."
            ),
        )

    return SqlIntervalMetricSource(pool=pool, flow_client=flow_client)
async def get_chart_labels(request: Request) -> ChartLabels:
    """Return the cached chart-label snapshot, refreshing if stale.

    The snapshot is loaded once at startup (``main.py`` lifespan). This
    provider checks the snapshot's age on every call; when older than
    ``LABEL_CACHE_TTL_SECONDS`` it acquires the app-level lock and
    reloads (single-flight against the source). Refresh failures log
    a warning but keep the previous snapshot in place, so a transient
    SQL hiccup doesn't blank labels out from the dashboard.

    Always returns a ``ChartLabels`` instance, even when the source
    is unavailable (e.g. SQL pool didn't initialize). An empty
    snapshot is harmless: ``ChartLabels.resolve()`` falls through to
    the raw metric key.
    """
    state = request.app.state
    labels = getattr(state, "chart_labels", None) or ChartLabels()
    source = getattr(state, "chart_label_source", None)
    lock = getattr(state, "chart_labels_lock", None)

    # Nothing to refresh against -- return whatever we have (possibly
    # empty). Routes still function; chart titles fall back to the
    # raw metric keys.
    if source is None or lock is None:
        return labels

    if time.monotonic() - labels.loaded_at <= LABEL_CACHE_TTL_SECONDS:
        return labels

    async with lock:
        # Re-check after acquiring the lock: another request may have
        # refreshed while we waited.
        labels = getattr(state, "chart_labels", None) or ChartLabels()
        if time.monotonic() - labels.loaded_at <= LABEL_CACHE_TTL_SECONDS:
            return labels
        try:
            fresh = await source.load()
            state.chart_labels = fresh
            return fresh
        except Exception as exc:  # noqa: BLE001 -- degrade gracefully
            _log.warning(
                "chart_labels.refresh_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
                stale_seconds=time.monotonic() - labels.loaded_at,
            )
            return labels
