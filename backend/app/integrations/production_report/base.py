"""Production-report source Protocol and shared types.

Every production-report source implements ``ProductionReportSource``.
Routes / services depend on the Protocol, never on a concrete class --
swapping sources is a DI change, not a code change.

As of Phase 13 (2026-04-28), ``SqlProductionReportSource`` is the
only production implementation. A test-only CSV-backed implementation
lives under ``tests/_fixtures/csv_source.py`` and is wired only via
``conftest.py``'s dependency overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

# Payload string values that mean "no value" rather than real content.
# Mirrors the frontend's placeholderize() convention ("_" / "None" /
# blank render as an em-dash) so a placeholder Description is treated as
# absent and falls back to the numeric department id.
_DEPT_NAME_PLACEHOLDERS: frozenset[str] = frozenset({"", "None"})


def workcenter_description(payload: dict[str, Any] | None) -> str | None:
    """Resolve the department label from ``Metrics.Workcenter.Description``.

    Returns the normalized description string, or ``None`` when the field
    is absent, non-string, or a placeholder -- letting the caller apply
    its own ``f"Dept {id}"`` fallback (and log, if it wants to).

    Normalization mirrors the retired ``[DailyProductionEntry].[dbo].``
    ``[Departments]`` convention: underscores become spaces, then the
    value is stripped. A value that reduces to empty (e.g. a bare ``"_"``)
    or equals the ``"None"`` sentinel is treated as a placeholder and
    yields ``None``.

    Single source of truth for the label so every surface (dashboard
    header, Trends left-nav + charts, circuit/product rollups, XLSX
    export) and every ``ProductionReportSource`` implementation resolve
    the name identically.
    """
    if not isinstance(payload, dict):
        return None
    metrics = payload.get("Metrics")
    if not isinstance(metrics, dict):
        return None
    workcenter = metrics.get("Workcenter")
    if not isinstance(workcenter, dict):
        return None
    raw = workcenter.get("Description")
    if not isinstance(raw, str):
        return None
    cleaned = raw.replace("_", " ").strip()
    if cleaned in _DEPT_NAME_PLACEHOLDERS:
        return None
    return cleaned


@dataclass(frozen=True)
class SourceStatus:
    """Outcome of a single source health check."""

    ok: bool
    detail: str
    checked_at: datetime


@dataclass(frozen=True)
class ProductionReportRow:
    """Parsed production-report row, source-agnostic.

    ``payload`` is the already-parsed PAYLOAD JSON as a plain dict.
    We intentionally do not model its inner shape here -- it's still
    stabilizing upstream and the schema varies between legacy and
    current rows. Callers treat it as data, not structure, for now.

    ``dtm`` is the upstream write timestamp. The SQL table allows NULL
    on this column, so the field is ``datetime | None``. The SQL source
    returns None when the row's DTM is NULL. Services handle None by
    treating it as the oldest possible timestamp for sort-ordering
    purposes.

    Enrichment fields (Phase 8) come from joins against
    ``SITE_PRODUCTION_RUN_HISTORY`` (shift, weather) and
    ``SITE_PRODUCTION_RUN_COMMENTS`` (notes). All default to ``None``;
    SQL rows whose LEFT JOIN misses (e.g. a production report with no
    history row yet) report None field-by-field.

    ``department_name`` is resolved from the report payload's
    ``Metrics.Workcenter.Description`` via :func:`workcenter_description`.
    The source synthesizes a ``f"Dept {department_id}"`` fallback (and
    logs a warning) when Description is absent or a placeholder, so this
    field is always populated in production responses -- the frontend
    can display it without null-check fallbacks. Underscores in the
    description are normalized to spaces.

    (Through Phase 32 this came from a cross-database LEFT JOIN against
    ``[DailyProductionEntry].[dbo].[Departments]``; that join was
    removed once ``Workcenter.Description`` became the authoritative
    label source -- see
    ``tasks/decisions/005-department-name-from-payload.md``.)

    No ``| None`` default: every source must populate this field.
    Phase 13 (2026-04-28) made SQL the only production source and
    tightened the contract.
    """

    id: int
    prod_date: datetime
    prod_id: str
    site_id: str
    department_id: str
    department_name: str
    payload: dict[str, Any]
    dtm: datetime | None
    # Phase 8 enrichment. Optional, default None.
    shift: str | None = field(default=None)
    weather_conditions: str | None = field(default=None)
    avg_temp: float | None = field(default=None)
    avg_humidity: float | None = field(default=None)
    max_wind_speed: float | None = field(default=None)
    notes: str | None = field(default=None)


@runtime_checkable
class ProductionReportSource(Protocol):
    """Contract every production-report source must satisfy.

    ``name`` is a short identifier used in health-check output.
    All methods are async so that current and future implementations
    compose cleanly; blocking sources wrap their work in
    ``asyncio.to_thread``.
    """

    name: str

    async def ping(self) -> SourceStatus: ...

    async def fetch_rows(self) -> list[ProductionReportRow]: ...

    async def list_site_ids(self) -> list[str]:
        """Return the distinct site IDs present in this source.

        Default implementation derives from ``fetch_rows`` -- concrete
        implementations override this with a cheaper path (e.g. SELECT
        DISTINCT in SQL) when possible.
        """
        ...
