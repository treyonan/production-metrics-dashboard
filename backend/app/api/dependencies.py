"""FastAPI dependency providers.

Every dependency lives here so route handlers stay thin. The
production-report provider branches on ``Settings.production_report_backend``:
CSV returns the file-backed implementation; SQL grabs the pool from
``app.state`` (populated in main.py's lifespan) and hands it to
``SqlProductionReportSource``.

Why no ``lru_cache``: the SQL path needs the per-request ``Request`` to
reach ``request.app.state.sql_pool``. Caching on an empty key would
outlive the pool. Both concrete sources are cheap to construct per
request (they just hold references), so dropping the cache costs
nothing meaningful.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.core.config import get_settings
from app.integrations.production_report.base import ProductionReportSource
from app.integrations.production_report.csv_source import CsvProductionReportSource
from app.integrations.production_report.sql_source import SqlProductionReportSource


def get_production_report_source(request: Request) -> ProductionReportSource:
    """Return the configured production-report source.

    Branches on ``Settings.production_report_backend`` so swapping
    CSV/SQL is a config change. CSV is the permanent test fixture and
    the default backend.
    """
    settings = get_settings()
    if settings.production_report_backend == "sql":
        pool = getattr(request.app.state, "sql_pool", None)
        if pool is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "SQL source unavailable: pool not initialized. "
                    "Check uvicorn startup log for 'sql_pool.create_failed' or "
                    "'sql_pool.not_created'."
                ),
            )
        return SqlProductionReportSource(pool=pool)
    return CsvProductionReportSource(settings.production_report_csv_path)


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
