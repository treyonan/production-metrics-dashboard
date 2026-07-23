"""FastAPI application entry point.

Import path for uvicorn: ``app.main:app``. Run from the ``backend/``
directory with the venv activated::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

from app.api.routes import dio, health, metrics, production_report, sites, timebase
from app.core.config import get_settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.logging import configure_logging, get_logger
from app.core.snapshot import InMemorySnapshotStore
from app.integrations.external.flow_client import FlowClient
from app.integrations.production_report.labels import (
    ChartLabels,
    SqlChartLabelSource,
)
from app.integrations.sql.pool import create_pool
from app.integrations.timebase.cache import TimebaseHistoryCache
from app.integrations.timebase.catalog import load_catalog as load_timebase_catalog
from app.integrations.timebase.client import TimebaseClient, TimebaseClientRegistry

BUILD_TAG = "2026-05-21-phase26-timebase-trends-page"


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

    # Chart labels (Phase 25): load once at startup, refresh on TTL via
    # the dependency provider. The labels resolver always returns a
    # graceful fallback (raw metric key) so missing rows / failed load
    # never breaks chart rendering.
    app.state.chart_label_source = None
    app.state.chart_labels = ChartLabels()
    app.state.chart_labels_lock = asyncio.Lock()
    if app.state.sql_pool is not None:
        try:
            source = SqlChartLabelSource(pool=app.state.sql_pool)
            app.state.chart_label_source = source
            app.state.chart_labels = await source.load()
            log.info(
                "chart_labels.initialized",
                row_count=app.state.chart_labels.row_count,
            )
        except Exception as exc:  # noqa: BLE001 -- degrade gracefully
            log.error(
                "chart_labels.initial_load_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    # Phase 9: Flow API client + in-process SnapshotStore.
    # Both are created unconditionally (even if no Flow keys are set)
    # so /api/metrics/* can return a clean 503 from its DI provider
    # rather than 500 from a missing app.state attribute.
    #
    # Phase 27.1 (2026-06-03): Flow auth is now per-site -- each Flow
    # installation has its own bearer token. Build the api_keys dict
    # by walking the configured sites and pulling any per-site key
    # set in settings (PMD_FLOW_API_KEY_<id>). The legacy
    # PMD_FLOW_API_KEY survives as the default fallback for any site
    # without its own key, so single-site deployments keep working
    # with no env var change.
    app.state.snapshot_store = InMemorySnapshotStore()
    app.state.flow_client = None

    per_site_keys: dict[str, str] = {}
    for sid in settings.site_names:
        key = settings.resolve_flow_api_key(sid)
        # Only put per-site keys in the dict (not the fallback) so
        # the client's "key not found for this site_id" check has
        # something meaningful to fall back to.
        explicit = getattr(settings, f"flow_api_key_{sid}", None)
        if explicit is not None:
            per_site_keys[sid] = explicit.get_secret_value()
    default_key = (
        settings.flow_api_key.get_secret_value()
        if settings.flow_api_key is not None
        else None
    )

    if per_site_keys or default_key is not None:
        try:
            client = FlowClient(
                api_keys=per_site_keys,
                default_api_key=default_key,
                timeout_seconds=settings.flow_api_timeout_seconds,
            )
            await client.aopen()
            app.state.flow_client = client
            log.info(
                "flow_client.created",
                per_site_key_sites=sorted(per_site_keys.keys()),
                default_key_set=default_key is not None,
            )
        except Exception as exc:  # noqa: BLE001 -- degrade-gracefully
            log.error(
                "flow_client.create_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
    else:
        log.info(
            "flow_client.not_created",
            reason=(
                "Neither PMD_FLOW_API_KEY nor any per-site "
                "PMD_FLOW_API_KEY_<id> is set; /api/metrics/* will 503"
            ),
        )

    # Phase 26: Timebase i3X integration. Each site has its own
    # historian on its own plant network; the URL lives in the
    # catalog YAML (sites.<id>.base_url). When the kill switch is
    # off (PMD_TIMEBASE_ENABLED=false), the entire block is skipped
    # -- no catalog load, no clients, no /api/health pings.
    app.state.timebase_catalog = None
    app.state.timebase_clients = None
    app.state.timebase_history_cache = None
    if not settings.timebase_enabled:
        log.info(
            "timebase.disabled",
            reason="PMD_TIMEBASE_ENABLED=false; skipping all Timebase init",
        )
    else:
        app.state.timebase_clients = TimebaseClientRegistry()
        app.state.timebase_history_cache = TimebaseHistoryCache(
            ttl_seconds=settings.timebase_cache_ttl_seconds,
            max_entries=settings.timebase_cache_max_entries,
        )
        try:
            app.state.timebase_catalog = load_timebase_catalog()
            log.info(
                "timebase.catalog_loaded",
                site_count=len(app.state.timebase_catalog.sites),
                asset_class_count=len(app.state.timebase_catalog.asset_classes),
            )
        except Exception as exc:  # noqa: BLE001 -- degrade gracefully
            log.error(
                "timebase.catalog_load_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        if app.state.timebase_catalog is None:
            log.info(
                "timebase.registry_not_populated",
                reason="catalog failed to load; /api/timebase/* will 503/404",
            )
        else:
            for site in app.state.timebase_catalog.sites.values():
                try:
                    tb_client = TimebaseClient(
                        site_id=site.site_id,
                        base_url=site.base_url,
                        dataset=site.dataset,
                        timeout_seconds=settings.timebase_timeout_seconds,
                    )
                    await tb_client.aopen()
                    app.state.timebase_clients.add(tb_client)
                    log.info(
                        "timebase.client_created",
                        site_id=site.site_id,
                        code=site.code,
                        base_url=site.base_url,
                    )
                except Exception as exc:  # noqa: BLE001 -- per-site degrade
                    log.error(
                        "timebase.client_create_failed",
                        site_id=site.site_id,
                        code=site.code,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )

    try:
        yield
    finally:
        # Close all per-site Timebase clients first, then Flow, then SQL pool.
        registry = getattr(app.state, "timebase_clients", None)
        if registry is not None:
            try:
                closed = registry.site_ids()
                await registry.aclose_all()
                if closed:
                    log.info("timebase.clients_closed", site_ids=closed)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "timebase.clients_close_failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
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
            {
                "name": "Interval Metrics",
                "description": "Time-series telemetry from Flow (hourly/shiftly).",
            },
            {
                "name": "Timebase",
                "description": (
                    "Raw historian samples + tag catalog from the "
                    "Timebase Historian i3X API."
                ),
            },
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
    app.include_router(dio.router, prefix="/api/dio", tags=["DIO"])
    app.include_router(metrics.router, prefix="/api/metrics", tags=["Interval Metrics"])
    app.include_router(timebase.router, prefix="/api/timebase", tags=["Timebase"])

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
