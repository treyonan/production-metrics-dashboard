"""Site lookup service.

Bridges site IDs reported by the production-report source with the
human-readable names configured in settings. Unknown IDs fall through
to a generic "Site <id>" label rather than raising -- the dashboard
should still render a functional selector even if settings are stale.

The result set is the **union** of two sources:

* Configured site_names (settings.site_names / _DEFAULT_SITE_NAMES).
  Includes commissioned-but-empty sites so the dashboard's site
  selector can pre-show them before SQL data arrives. Listing order
  matches the dict's insertion order, so config controls "which site
  is the default" (sites[0] in the API response).

* Sites observed in the source's data (SQL DISTINCT site_id). Catches
  any site that publishes data without a config entry; those get a
  fallback "Site <id>" display name. Appended after configured sites
  so adding data for a new uncommissioned site doesn't shift the
  default.

This means commissioning workflow is: edit `_DEFAULT_SITE_NAMES` in
config.py, ship -- and the site appears in the dropdown immediately,
selectable for deep-linking, even before any SQL rows land.
"""

from __future__ import annotations

from app.integrations.production_report.base import ProductionReportSource
from app.schemas.sites import SiteInfo


async def list_sites(
    source: ProductionReportSource,
    site_names: dict[str, str],
) -> list[SiteInfo]:
    """Return the union of configured + data-bearing sites.

    Configured order is preserved first, then any data-only ids
    appended. De-duplicates so an id present in both shows up
    exactly once.
    """
    data_ids = await source.list_site_ids()

    seen: set[str] = set()
    ordered: list[str] = []
    # Pass 1: configured sites (insertion order from settings.site_names).
    # config.py owns the default-site decision via dict ordering.
    for sid in site_names:
        if sid not in seen:
            seen.add(sid)
            ordered.append(sid)
    # Pass 2: data-only sites without a config entry. Fallback label.
    for sid in data_ids:
        if sid not in seen:
            seen.add(sid)
            ordered.append(sid)
    return [
        SiteInfo(id=sid, name=site_names.get(sid, f"Site {sid}"))
        for sid in ordered
    ]
