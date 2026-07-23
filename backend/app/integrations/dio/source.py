"""Operational DIO / Days-of-Supply source (Spec 005).

Executes the stored procedure ``UNS.GET_SITE_DIO_DAILY_RECORDS`` and maps
its result set to typed ``DioRecord`` rows.

Unlike ``ConfiguredRunReportSource`` (whose columns are config-driven and
therefore read from ``cursor.description``), this SP returns a FIXED,
known column set, so the source maps the result columns positionally onto
a typed dataclass. The order below MUST match the SP's final SELECT:

    0 Item Code
    1 Item Description
    2 Total Sales
    3 TPD of sales
    4 Current Inventory
    5 Days Of Inventory On Hand        (NULL when the item had no sales)
    6 Days Of Inventory After Shutdown (NULL when the item had no sales)

Read-only: the SP only SELECTs. The API's SQL account needs ``EXECUTE``
on ``UNS.GET_SITE_DIO_DAILY_RECORDS`` (and read on the underlying tables).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.integrations.sql.queries import load_query

if TYPE_CHECKING:
    import aioodbc

_QUERIES_DIR = Path(__file__).parent / "queries"
_log = get_logger("app.integrations.dio.source")

# Per-call wall-clock budget. Honours the project's "every integration
# call has a timeout" rule. The SP scans a per-item date window; a view
# refresh can tolerate a few seconds but not an unbounded hang.
DEFAULT_TIMEOUT_SECONDS = 30.0

# Number of columns the SP's SELECT returns, in order. Guards against a
# shape change surfacing as an IndexError instead of a clear message.
_EXPECTED_COLUMNS = 7


@dataclass(frozen=True)
class DioRecord:
    """One item's Days-of-Supply slice over the window (service-internal).

    Numeric fields are JSON-safe floats (Decimal coerced) or ``None``.
    ``days_on_hand`` / ``days_after_shutdown`` are ``None`` when the SP
    returned NULL (the item had zero sales in the window).
    """

    item_code: str
    item_description: str
    total_sales: float | None
    tpd_sales: float | None
    current_inventory: float | None
    days_on_hand: float | None
    days_after_shutdown: float | None


def _num(value: Any) -> float | None:
    """Coerce a numeric driver cell to ``float`` (or ``None``).

    Decimal -> float; int / float pass through as float; None and any
    non-numeric value -> None. bool is treated as non-numeric (the SP
    never returns bit columns here).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    """Coerce a text driver cell to ``str`` ("" for NULL)."""
    if value is None:
        return ""
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "replace")
    return str(value)


class DioSource:
    """Executes ``UNS.GET_SITE_DIO_DAILY_RECORDS`` via an aioodbc pool."""

    name = "sql:site_dio_daily_records"

    def __init__(self, pool: aioodbc.Pool, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._pool = pool
        self._timeout = timeout
        # Load at construction -- fail fast if the .sql file is missing.
        self._sql = load_query(_QUERIES_DIR, "site_dio_daily_records")

    async def fetch_records(
        self,
        *,
        site_id: str,
        start: datetime,
        end: datetime,
    ) -> list[DioRecord]:
        """Run the SP for one (site, window) and map rows to ``DioRecord``.

        ``site_id`` is str in the API's contract but the SP's param is
        INT, so it's cast here. Raises on driver / timeout errors and on
        an unexpected column count -- the service turns that into a 503.
        """
        params = (int(site_id), start, end)

        async def _run() -> list[DioRecord]:
            async with (
                self._pool.acquire() as conn,
                conn.cursor() as cur,
            ):
                await cur.execute(self._sql, *params)
                description = cur.description or []
                raw_rows = await cur.fetchall()
            col_count = len(description)
            if col_count < _EXPECTED_COLUMNS:
                raise RuntimeError(
                    "UNS.GET_SITE_DIO_DAILY_RECORDS returned "
                    f"{col_count} columns; expected {_EXPECTED_COLUMNS}."
                )
            return [
                DioRecord(
                    item_code=_text(row[0]),
                    item_description=_text(row[1]),
                    total_sales=_num(row[2]),
                    tpd_sales=_num(row[3]),
                    current_inventory=_num(row[4]),
                    days_on_hand=_num(row[5]),
                    days_after_shutdown=_num(row[6]),
                )
                for row in raw_rows
            ]

        return await asyncio.wait_for(_run(), timeout=self._timeout)
