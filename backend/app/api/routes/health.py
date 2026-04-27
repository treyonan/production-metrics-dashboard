"""/api/health -- per-source reachability for the dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_production_report_source
from app.core.config import Settings, get_settings
from app.integrations.production_report.base import ProductionReportSource
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
    settings: SettingsDep,
    production_report: ProductionReportSourceDep,
) -> HealthResponse:
    # With more sources this becomes ``asyncio.gather(*source.ping() for ...)``.
    pr_status = await production_report.ping()

    sources = [
        SourceHealth(
            name=production_report.name,
            ok=pr_status.ok,
            detail=pr_status.detail,
            checked_at=pr_status.checked_at,
        )
    ]

    return HealthResponse(
        status=_derive_overall(sources),  # type: ignore[arg-type]
        version=settings.api_version,
        environment=settings.environment,
        checked_at=datetime.now(UTC),
        sources=sources,
    )
