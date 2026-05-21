"""/api/health -- per-source reachability for the dashboard."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_production_report_source
from app.core.config import Settings, get_settings
from app.integrations.production_report.base import ProductionReportSource
from app.integrations.timebase.client import TimebaseClient, TimebaseClientRegistry
from app.schemas.health import HealthResponse, SourceHealth

router = APIRouter()

SettingsDep = Annotated[Settings, Depends(get_settings)]
ProductionReportSourceDep = Annotated[ProductionReportSource, Depends(get_production_report_source)]


def _derive_overall(sources: list[SourceHealth]) -> str:
    if not sources:
        return "ok"
    ok = sum(1 for s in sources if s.ok)
    if ok == len(sources):
        return "ok"
    if ok == 0:
        return "down"
    return "degraded"


async def _ping_timebase_client(client: TimebaseClient) -> SourceHealth:
    """Cheap reachability check against one site's i3X /namespaces.

    Returns a ``SourceHealth`` with ``ok=False`` and the upstream error
    in ``detail`` on any failure. The ``name`` carries the site_id so
    the dashboard can show per-site historian health (e.g.
    'timebase:i3x:101').
    """
    checked_at = datetime.now(UTC)
    try:
        ns = await client.get_namespaces()
    except (httpx.HTTPError, RuntimeError) as exc:
        return SourceHealth(
            name=client.name,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            checked_at=checked_at,
        )
    return SourceHealth(
        name=client.name,
        ok=True,
        detail=f"{len(ns)} namespace(s) returned",
        checked_at=checked_at,
    )


async def _ping_all_timebase_sites(
    registry: TimebaseClientRegistry | None,
) -> list[SourceHealth]:
    """Ping every configured site in parallel.

    Empty list when the registry is missing or contains no clients --
    a deployment with no Timebase historian configured doesn't ring
    the 'degraded' bell.
    """
    if registry is None or len(registry) == 0:
        return []
    return list(
        await asyncio.gather(*(_ping_timebase_client(c) for c in registry))
    )


@router.get(
    "",
    response_model=HealthResponse,
    summary="Per-source reachability",
    description=(
        "Returns overall API status plus per-source reachability. The "
        "dashboard uses this to show which data sources are up per tile "
        "rather than blanking the whole page when one source is slow."
    ),
)
async def get_health(
    request: Request,
    settings: SettingsDep,
    production_report: ProductionReportSourceDep,
) -> HealthResponse:
    pr_status = await production_report.ping()

    sources: list[SourceHealth] = [
        SourceHealth(
            name=production_report.name,
            ok=pr_status.ok,
            detail=pr_status.detail,
            checked_at=pr_status.checked_at,
        )
    ]

    # Phase 26: ping every configured Timebase site. Each site gets
    # its own SourceHealth entry so the dashboard can show "Big Canyon
    # historian: up, Ardmore historian: down" independently. Empty
    # registry adds nothing -- deployments without Timebase don't
    # show as "degraded".
    registry: TimebaseClientRegistry | None = getattr(
        request.app.state, "timebase_clients", None
    )
    sources.extend(await _ping_all_timebase_sites(registry))

    return HealthResponse(
        status=_derive_overall(sources),  # type: ignore[arg-type]
        version=settings.api_version,
        environment=settings.environment,
        checked_at=datetime.now(UTC),
        sources=sources,
    )
