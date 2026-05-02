"""FastAPI application entry point.

Import path for uvicorn: ``app.main:app``. Run from the ``backend/``
directory with the venv activated::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

from app.api.routes import health, metrics, production_report, sites
from app.core.config import get_settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.logging import configure_logging, get_logger
from app.core.snapshot import InMemorySnapshotStore
from app.integrations.external.flow_client import FlowClient
from app.integrations.sql.pool import create_pool

BUILD_TAG = "2026-05-01-phase18-rollup-bucket"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("app.main")
    log.info(
        "app.startup",
        build_tag=BUILD_TAG,
        environment=settings.environment,
        version=settings.api_version,
        frontend_dir=str(settings.frontend_dir),
        frontend_dir_is_dir=settings.frontend_dir.is_dir(),
    )

    # SQL pool -- the only production-report source path as of Phase 13.
    # If creation fails (bad DSN, driver missing, network unreachable),
    # we stay up and degraded: /api/health surfaces the unhealthy
    # source and /api/production-report/* returns 503 via the DI
    # provider rather than 500.
    app.state.sql_pool = None
    if settings.db_conn_string is None:
        log.error(
            "sql_pool.not_created",
            reason="DB_CONN_STRING not set; /api/production-report/* will 503",
        )
    else:
        try:
            app.state.sql_pool = await create_pool(settings.db_conn_string.get_secret_value())
            log.info("sql_pool.created")
        except Exception as exc:  # noqa: BLE001 -- degrade-gracefully on any driver error
            log.error(
                "sql_pool.create_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    # Phase 9: Flow API client + in-process SnapshotStore.
    # Both are created unconditionally (even if FLOW_API_KEY is unset)
    # so /api/metrics/* can return a clean 503 from its DI provider
    # rather than 500 from a missing app.state attribute.
    app.state.snapshot_store = InMemorySnapshotStore()
    app.state.flow_client = None
    if settings.flow_api_key is not None:
        try:
            client = FlowClient(
                api_key=settings.flow_api_key.get_secret_value(),
                timeout_seconds=settings.flow_api_timeout_seconds,
            )
            await client.aopen()
            app.state.flow_client = client
            log.info("flow_client.created")
        except Exception as exc:  # noqa: BLE001 -- degrade-gracefully
            log.error(
                "flow_client.create_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
    else:
        log.info(
            "flow_client.not_created",
            reason="FLOW_API_KEY not set; /api/metrics/* will 503",
        )

    try:
        yield
    finally:
        # Close the Flow client first (HTTP), then the SQL pool.
        flow_client = getattr(app.state, "flow_client", None)
        if flow_client is not None:
            try:
                await flow_client.aclose()
                log.info("flow_client.closed")
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "flow_client.close_failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
        pool = getattr(app.state, "sql_pool", None)
        if pool is not None:
            try:
                pool.close()
                await pool.wait_closed()
                log.info("sql_pool.closed")
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "sql_pool.close_failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
        log.info("app.shutdown")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "Read-only API aggregating production metrics from SQL Server, "
            "external REST APIs, and the Ignition historian for a polling "
            "plant dashboard (1-5 min cadence)."
        ),
        openapi_tags=[
            {"name": "Health", "description": "Per-source reachability checks."},
            {"name": "Sites", "description": "Enumeration of sites present in the data source."},
            {"name": "Production Report", "description": "Workcenter production KPIs."},
            {"name": "Interval Metrics", "description": "Time-series telemetry from Flow (hourly/shiftly)."},
        ],
        lifespan=lifespan,
    )
    app.add_middleware(CorrelationIdMiddleware)

    # API routes
    app.include_router(health.router, prefix="/api/health", tags=["Health"])
    app.include_router(sites.router, prefix="/api/sites", tags=["Sites"])
    app.include_router(
        production_report.router,
        prefix="/api/production-report",
        tags=["Production Report"],
    )
    app.include_router(metrics.router, prefix="/api/metrics", tags=["Interval Metrics"])

    # Debug ping (under /api/ so it's not shadowed by any static mount).
    @app.get("/api/__ping", include_in_schema=False)
    async def ping() -> dict:
        return {"alive": True, "build_tag": BUILD_TAG}

    # Static frontend. Explicit root handler registered BEFORE the mount,
    # so GET "/" is served by the explicit handler rather than falling
    # through to the mount's index behavior.
    fd = settings.frontend_dir
    index_html = fd / "index.html" if fd else None

    if fd and fd.is_dir() and index_html and index_html.is_file():

        @app.get("/", include_in_schema=False)
        async def root_index() -> FileResponse:
            return FileResponse(index_html)

        app.mount("/", StaticFiles(directory=fd, html=True), name="frontend")
        print(f"[main] build={BUILD_TAG} static_root={fd}")
    else:
        print(
            f"[main] build={BUILD_TAG} Static frontend NOT mounted -- "
            f"frontend_dir={fd!s} is_dir={fd.is_dir() if fd else False} "
            f"index_html_exists={index_html.is_file() if index_html else False}"
        )

    # Dump registered routes at startup so we can see order in the console.
    print("[main] Registered routes (in order):")
    for i, route in enumerate(app.routes):
        path = getattr(route, "path", getattr(route, "path_format", "(?)"))
        kind = "Mount" if isinstance(route, Mount) else type(route).__name__
        print(f"  {i:2d}. {kind:12s} {path or '(root-mount)'}")

    return app


app = create_app()
