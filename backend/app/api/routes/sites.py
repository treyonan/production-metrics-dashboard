"""/api/sites -- enumeration of sites present in the current data source."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_production_report_source
from app.core.config import Settings, get_settings
from app.integrations.production_report.base import ProductionReportSource
from app.schemas.sites import SitesResponse
from app.services.sites import list_sites

router = APIRouter()

SettingsDep = Annotated[Settings, Depends(get_settings)]
ProductionReportSourceDep = Annotated[ProductionReportSource, Depends(get_production_report_source)]


@router.get(
    "",
    response_model=SitesResponse,
    summary="Sites available in the data source",
    description=(
        "Returns the list of sites present in the production-report source, "
        "each annotated with its display name. The dashboard uses this to "
        "populate the site selector."
    ),
)
async def list_sites_endpoint(
    settings: SettingsDep,
    source: ProductionReportSourceDep,
) -> SitesResponse:
    sites = await list_sites(source, settings.site_names)
    return SitesResponse(count=len(sites), sites=sites)
