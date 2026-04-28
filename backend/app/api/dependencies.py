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

from fastapi import HTTPException, Request

from app.integrations.production_report.base import ProductionReportSource
from app.integrations.production_report.sql_source import SqlProductionReportSource


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


def get_interval_metric_source(request: Request):
    """Return the configured interval-metric source.

    Today only one implementation: ``SqlIntervalMetricSource`` reading
    from ``[FLOW].[INTERVAL_METRIC_TAGS]`` and fanning out to Flow's
    REST API. Returns 503 from this provider when either dependency
    is missing -- the SQL pool (lifespan-created when the SQL backend
    is selected) or the FlowClient (lifespan-created when
    ``FLOW_API_KEY`` is set in env).
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
