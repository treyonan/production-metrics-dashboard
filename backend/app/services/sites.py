"""Site lookup service.

Bridges site IDs reported by the production-report source with the
human-readable names configured in settings. Unknown IDs fall through
to a generic "Site <id>" label rather than raising -- the dashboard
should still render a functional selector even if settings are stale.
"""

from __future__ import annotations

from app.integrations.production_report.base import ProductionReportSource
from app.schemas.sites import SiteInfo


async def list_sites(
    source: ProductionReportSource,
    site_names: dict[str, str],
) -> list[SiteInfo]:
    """Return the sites available in the source, with display names."""
    ids = await source.list_site_ids()
    return [SiteInfo(id=sid, name=site_names.get(sid, f"Site {sid}")) for sid in ids]
