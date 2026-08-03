"""SQL Server-backed production-report source.

Reads from ``IA_ENTERPRISE.[UNS].[SITE_PRODUCTION_RUN_REPORTS]``
(plus two LEFT JOINs for shift/weather and notes) via an aioodbc
connection pool. The only production-report source as of Phase 13.

Type-contract notes:

* ``SITE_ID`` and ``DEPARTMENT_ID`` are ``int`` in SQL; this source
  casts them to ``str`` to match the JSON contract and the frontend's
  string comparisons.
* ``DTM`` is nullable in SQL; ``ProductionReportRow.dtm`` is
  ``datetime | None``. The service layer treats ``None`` as oldest
  for sort-ordering.
* ``PAYLOAD`` is ``nvarchar(max)`` holding a JSON string; we
  ``json.loads`` it on the Python side.
* Phase 8 enrichment fields (SHIFT, WEATHER_CONDITIONS, AVG_TEMP,
  AVG_HUMIDITY, MAX_WIND_SPEED, NOTES) come from LEFT JOINs and
  can be NULL. Numeric columns are converted to ``float`` for
  JSON serialization compatibility; ``None`` passes through.
* ``department_name`` is resolved from the payload's
  ``Metrics.Workcenter.Description`` via
  :func:`app.integrations.production_report.base.workcenter_description`
  (shared with the test fixture so both resolve identically). The
  dataclass field is non-null; this source synthesizes ``f"Dept {id}"``
  when Description is absent or a placeholder. A *recent* report missing
  it logs at WARNING (an actionable upstream regression); older/legacy
  reports -- which predate the field and would otherwise flood the log on
  the full-table scan -- log at DEBUG (see ``_RECENT_MISSING_WARN_DAYS``).
  (The cross-database ``[DailyProductionEntry].[dbo].[Departments]``
  join that formerly supplied this value was removed -- see
  ``tasks/decisions/005-department-name-from-payload.md``.)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from app.core.logging import get_logger
from app.integrations.sql.queries import load_query

from .base import ProductionReportRow, SourceStatus, workcenter_description

if TYPE_CHECKING:
    import aioodbc

_QUERIES_DIR = Path(__file__).parent / "queries"
_log = get_logger("app.integrations.production_report.sql_source")

# A report missing Metrics.Workcenter.Description only signals a real
# upstream regression when it is *recent*. Legacy reports predate the
# field and will never have it; on the parameterless full-table scan they
# would otherwise re-warn on every poll. Reports older than this cutoff
# (in days, by prod_date) log the fallback at DEBUG instead of WARNING.
_RECENT_MISSING_WARN_DAYS: Final[int] = 7


def _is_recent_report(prod_date: Any, *, now: datetime | None = None) -> bool:
    """Whether ``prod_date`` falls within the recent-warning window.

    Drives the warn-vs-debug choice when a report is missing
    ``Workcenter.Description``: recent -> WARNING (actionable regression),
    older -> DEBUG (expected legacy gap). ``now`` is injectable for tests;
    it defaults to the current time in ``prod_date``'s tz (or naive).
    Non-datetime ``prod_date`` is treated as not recent.
    """
    if not isinstance(prod_date, datetime):
        return False
    ref = now if now is not None else datetime.now(prod_date.tzinfo)
    return (ref - prod_date).days <= _RECENT_MISSING_WARN_DAYS


def _to_float_or_none(v: Any) -> float | None:
    """Coerce a numeric column (possibly Decimal) to float, preserving None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class SqlProductionReportSource:
    """Reads production-report rows from SQL Server via aioodbc."""

    name = "sql:production_report"

    def __init__(self, pool: aioodbc.Pool) -> None:
        self._pool = pool
        # Load queries at construction time; fails fast if a .sql file
        # is missing rather than waiting until the first request.
        self._ping_sql = load_query(_QUERIES_DIR, "ping")
        self._select_all_sql = load_query(_QUERIES_DIR, "select_all")

    async def ping(self) -> SourceStatus:
        """Run ``SELECT 1`` to verify the pool can execute a query."""
        now = datetime.now(UTC)
        try:
            async with (
                self._pool.acquire() as conn,
                conn.cursor() as cur,
            ):
                await cur.execute(self._ping_sql)
                row = await cur.fetchone()
            if row is not None and row[0] == 1:
                return SourceStatus(
                    ok=True,
                    detail="SELECT 1 returned 1",
                    checked_at=now,
                )
            return SourceStatus(
                ok=False,
                detail=f"Unexpected ping result: {row!r}",
                checked_at=now,
            )
        except Exception as exc:  # noqa: BLE001 -- diagnostic: any error means unhealthy
            return SourceStatus(
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                checked_at=now,
            )

    async def fetch_rows(self) -> list[ProductionReportRow]:
        """Return every row from the joined production-report query."""
        async with (
            self._pool.acquire() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(self._select_all_sql)
            raw_rows = await cur.fetchall()
        return [self._row_to_dataclass(r) for r in raw_rows]

    async def list_site_ids(self) -> list[str]:
        """Derive distinct site IDs from a full-table fetch."""
        rows = await self.fetch_rows()
        return sorted({r.site_id for r in rows})

    @staticmethod
    def _row_to_dataclass(row: Any) -> ProductionReportRow:
        """Convert a driver row tuple into a typed ProductionReportRow.

        Column order matches ``queries/select_all.sql``:
          0=ID             1=PRODDATE       2=PROD_ID
          3=SITE_ID        4=DEPARTMENT_ID  5=PAYLOAD   6=DTM
          7=SHIFT          8=WEATHER_CONDITIONS
          9=AVG_TEMP      10=AVG_HUMIDITY  11=MAX_WIND_SPEED
         12=NOTES
        """
        payload_raw = row[5]
        payload: dict[str, Any] = json.loads(payload_raw) if payload_raw else {}

        # department_name is resolved from the payload's
        # Metrics.Workcenter.Description (shared resolver, so the test
        # fixture and this source stay in lockstep). The field is
        # non-null in the source-row contract; Description should always
        # be present in production, but on an absent/placeholder value we
        # synthesize a deterministic "Dept <id>" fallback and log a
        # warning so the data-integrity issue is visible without taking
        # the request down.
        department_id = str(row[4])
        resolved = workcenter_description(payload)
        if resolved is None:
            # Only a RECENT report missing the field is actionable (an
            # upstream regression). Legacy reports predate the field and
            # are expected to miss it; on a full-table scan they'd flood
            # the log every poll, so they drop to DEBUG.
            prod_date = row[1]
            is_recent = _is_recent_report(prod_date)
            log = _log.warning if is_recent else _log.debug
            log(
                "department_name.workcenter_description_missing",
                department_id=department_id,
                prod_id=row[2],
                prod_date=(
                    prod_date.isoformat()
                    if isinstance(prod_date, datetime)
                    else None
                ),
                recent=is_recent,
                hint=(
                    "payload.Metrics.Workcenter.Description was absent or a "
                    "placeholder; surfacing 'Dept <id>' fallback. A recent "
                    "report missing this indicates an upstream regression; "
                    "legacy reports predate the field and are expected."
                ),
            )
            department_name = f"Dept {department_id}"
        else:
            department_name = resolved

        return ProductionReportRow(
            id=int(row[0]),
            prod_date=row[1],
            prod_id=row[2],
            site_id=str(row[3]),  # int -> str
            department_id=department_id,  # int -> str
            department_name=department_name,
            payload=payload,
            dtm=row[6],  # may be None (DTM column is nullable)
            # SHIFT is INT in the HISTORY schema (values like 0, 1 per
            # Trey's sample). Coerce to str at the source boundary to
            # match the JSON contract (string identifiers). Same pattern
            # as SITE_ID / DEPARTMENT_ID above.
            shift=str(row[7]) if row[7] is not None else None,
            # WEATHER_CONDITIONS and NOTES are NVARCHAR -> str via ODBC.
            # Defensive str() makes a future column-type change a no-op.
            weather_conditions=str(row[8]) if row[8] is not None else None,
            avg_temp=_to_float_or_none(row[9]),
            avg_humidity=_to_float_or_none(row[10]),
            max_wind_speed=_to_float_or_none(row[11]),
            notes=str(row[12]) if row[12] is not None else None,
        )
