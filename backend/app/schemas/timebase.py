"""Pydantic schemas for /api/timebase/* endpoints.

Two shapes:

* History pass-through (``HistoryRequest`` / ``HistoryResponse``) --
  the wire format matches the upstream i3X spec exactly. Aliases
  preserve ``elementIds`` / ``startTime`` / ``endTime`` / ``maxDepth``
  on the wire while Python code uses snake_case. The response is a
  ``RootModel`` over the i3X dict-keyed-by-elementId shape so OpenAPI
  documents it without the FastAPI service re-shaping anything.

* Catalog (``CatalogResponse`` + nested ``CatalogSite`` /
  ``CatalogDepartment`` / ``CatalogAssetClass`` / ``CatalogAsset`` /
  ``CatalogMetric``) -- the resolved tag inventory per site, with
  full elementIds pre-computed. Phase 2's chart page hangs its
  asset/metric cascading-dropdowns off this.

See ``tasks/specs/003-timebase-i3x-wrapper.md`` for the design.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, RootModel

# ============================================================================
# History pass-through
# ============================================================================


class HistoryRequest(BaseModel):
    """Request body for ``POST /api/timebase/history?site_id=<id>``.

    Caller sends tag paths *under* the site's dataset; the server
    composes the full ``<dataset>:<tag_path>`` elementId from the
    YAML catalog. Identical from any caller (dashboard, Ignition,
    ad-hoc tools) -- the URL + dataset lookup happens server-side
    via ``site_id``.

    Wire format is snake_case (matches /api/metrics and
    /api/production-report). Not the raw i3X shape.
    """

    tag_paths: list[str] = Field(
        min_length=1,
        description=(
            "One or more tag paths (no dataset prefix, no leading "
            "slash). The server composes '<dataset>:<tag_path>' for "
            "each entry using the dataset from the site's catalog "
            "entry. Example: "
            "'Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH'."
        ),
    )
    start_time: datetime = Field(
        description=(
            "Inclusive window start (ISO-8601). Server normalizes "
            "to a 10-second UTC boundary for cache-key stability."
        ),
    )
    end_time: datetime = Field(
        description="Inclusive window end (ISO-8601).",
    )
    max_depth: int = Field(
        default=1,
        ge=0,
        description=(
            "i3X maxDepth. 0 = infinite, 1 = no recursion (default). "
            "For Tag elementIds this has no effect; included for "
            "upstream-shape compatibility."
        ),
    )


# i3X VQT values can be numeric, string, boolean, or null depending on
# the underlying tag. Keep it permissive -- this is a pass-through.
VqtValue = float | int | str | bool | None


class VQT(BaseModel):
    """One value-quality-timestamp sample.

    Field names match i3X exactly so the wire JSON is unmodified.
    """

    value: VqtValue = Field(
        description=(
            "The sampled value. Type follows the upstream tag's schema "
            "(numeric for analog tags, bool for discretes, etc.)."
        )
    )
    quality: str = Field(
        description=(
            "Vendor quality flag. Observed values include 'GOOD'; "
            "'BAD' and 'UNCERTAIN' are presumed valid per OPC-UA "
            "convention. Phase 1 forwards unmodified; Phase 2 UI "
            "may filter."
        )
    )
    timestamp: datetime = Field(
        description="UTC sample timestamp as ISO-8601."
    )


class ElementHistory(BaseModel):
    """The ``{ data: [VQT, ...] }`` block i3X returns per elementId."""

    data: list[VQT] = Field(
        description=(
            "Time-ordered VQT samples within the requested window. "
            "May be empty when the tag has no samples in range."
        )
    )


class HistoryResponse(RootModel[dict[str, ElementHistory]]):
    """Top-level history response: dict keyed by elementId.

    Pass-through shape -- the FastAPI service does not re-shape the
    upstream payload. Using ``RootModel`` instead of wrapping in an
    envelope keeps the wire format identical to i3X's, so existing
    i3X clients can target our endpoint without translation.
    """


# ============================================================================
# Catalog
# ============================================================================


class CatalogMetric(BaseModel):
    """One metric within an asset, with its resolved full elementId."""

    metric_key: str = Field(
        description=(
            "Stable internal key (e.g. 'belt_scale_tph'). Same across "
            "all sites for a given asset_class."
        )
    )
    display_name: str = Field(
        description="Human-readable label for dashboards (e.g. 'Belt Scale TPH')."
    )
    unit: str = Field(
        description=(
            "Engineering unit of the metric (e.g. 'tph', 'tons'). "
            "Empty string when the metric is unitless or unit is unknown."
        )
    )
    element_id: str = Field(
        description=(
            "Fully resolved i3X elementId for this site+asset+metric. "
            "Pass this directly to POST /api/timebase/history."
        )
    )


class CatalogAsset(BaseModel):
    """One asset (e.g. conveyor 'C1') and its available metrics."""

    asset: str = Field(description="Asset id (e.g. 'C1', 'C2').")
    metrics: list[CatalogMetric] = Field(
        description="Metrics defined for this asset_class, with resolved elementIds."
    )


class CatalogAssetClass(BaseModel):
    """One asset class within a department (e.g. 'Conveyor')."""

    asset_class: str = Field(
        description="Class name (e.g. 'Conveyor').",
        alias="class",
    )
    assets: list[CatalogAsset] = Field(
        description="Asset instances of this class at this site/department."
    )

    model_config = ConfigDict(populate_by_name=True)


class CatalogDepartment(BaseModel):
    """One department within a site (e.g. 'Secondary')."""

    name: str = Field(description="Department name as it appears in tag paths.")
    asset_classes: list[CatalogAssetClass] = Field(
        description="Asset classes present in this department."
    )


class CatalogSite(BaseModel):
    """One site's resolved catalog."""

    site_id: str = Field(description="Site identifier (matches Flow / SQL site_id).")
    code: str = Field(description="Short code (e.g. 'BCQ').")
    display_name: str = Field(description="Human-readable site name.")
    dataset: str = Field(
        description="Timebase dataset name (e.g. 'IAP_BCQ_Controls')."
    )
    departments: list[CatalogDepartment] = Field(
        description="Departments configured for this site."
    )


class CatalogResponse(BaseModel):
    """Envelope for /api/timebase/catalog.

    The single-site endpoint returns a ``CatalogResponse`` with one
    site in ``sites``; the all-sites endpoint returns every configured
    site. Same shape either way so the frontend has one parser.
    """

    sites: list[CatalogSite] = Field(
        description="Configured Timebase sites with resolved elementIds."
    )
