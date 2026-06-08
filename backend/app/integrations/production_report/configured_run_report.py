"""Configured Run Report source (Phase 31).

Executes the existing stored procedure ``UNS.GET_CONFIGURED_RUN_REPORT``
and returns its result set as ordered column names + row tuples. The
SP's column set is built dynamically from ``MES.RUN_REPORTS_CONFIG``
(per site + department), so this source is deliberately generic: it
reads ``cursor.description`` for the column names rather than mapping a
fixed schema the way ``SqlProductionReportSource`` does.

Read-only: the SP only SELECTs. The API's SQL account needs ``EXECUTE``
on ``UNS.GET_CONFIGURED_RUN_REPORT`` (and read on the underlying tables).

Why EXEC the SP here when ``select_all.sql`` deliberately does NOT EXEC
``UNS.GET_PRODUCTION_RUN_REPORTS``: that report has a fixed shape and is
on the hot polling path, so replicating its joins in a query file avoids
per-department round-trips. This report's columns are *dynamic* (config
-driven) and the export is *on-demand* (a button, not the 1-5 min poll),
so EXEC-ing the SP is both necessary and acceptable. See
``tasks/decisions/004-configured-run-report-sp.md``.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.integrations.sql.queries import load_query

if TYPE_CHECKING:
    import aioodbc

_QUERIES_DIR = Path(__file__).parent / "queries"
_log = get_logger("app.integrations.production_report.configured_run_report")

# Per-call wall-clock budget. Honours the project's "every integration
# call has a timeout" rule. Generous because the SP scans a date window
# across a department's reports; an export click can tolerate a few
# seconds, but not an unbounded hang on a wedged connection.
DEFAULT_TIMEOUT_SECONDS = 30.0


def _json_safe(value: Any) -> Any:
    """Coerce a driver cell value into a JSON-serializable form.

    The SP returns mostly strings (it CONVERTs Date and FORMATs times)
    plus some numerics. Decimal -> float, datetime/date -> ISO string,
    bytes -> decoded str; str / int / float / bool / None pass through.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 -- defensive; fall back to repr
            return str(value)
    return str(value)


class ConfiguredRunReportSource:
    """Executes ``UNS.GET_CONFIGURED_RUN_REPORT`` via an aioodbc pool."""

    name = "sql:configured_run_report"

    def __init__(self, pool: aioodbc.Pool, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._pool = pool
        self._timeout = timeout
        # Load at construction -- fail fast if the .sql file is missing.
        self._sql = load_query(_QUERIES_DIR, "configured_run_report")

    async def fetch_report(
        self,
        *,
        site_id: str,
        department_id: str,
        start: datetime,
        end: datetime,
    ) -> tuple[list[str], list[list[Any]]]:
        """Run the SP for one (site, department, window).

        Returns ``(columns, rows)`` where ``columns`` is the ordered list
        of display-name headers (from ``cursor.description``) and ``rows``
        is a list of JSON-safe value lists in the same column order.

        ``site_id`` / ``department_id`` are str in the API's contract but
        the SP's params are INT, so they're cast here. Raises on driver /
        timeout errors -- the service translates that into a 503.
        """
        params = (int(site_id), int(department_id), start, end)

        async def _run() -> tuple[list[str], list[list[Any]]]:
            async with (
                self._pool.acquire() as conn,
                conn.cursor() as cur,
            ):
                await cur.execute(self._sql, *params)
                # Dynamic result set: column names come from the cursor,
                # not a fixed mapping. description is None only when the
                # statement produced no result set (shouldn't happen --
                # the SP always SELECTs), so guard defensively.
                description = cur.description or []
                columns = [d[0] for d in description]
                raw_rows = await cur.fetchall()
            rows = [[_json_safe(cell) for cell in row] for row in raw_rows]
            return columns, rows

        return await asyncio.wait_for(_run(), timeout=self._timeout)
