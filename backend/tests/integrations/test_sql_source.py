"""Unit tests for SqlProductionReportSource.

Uses a fake ``aioodbc``-shaped pool so tests run without a real SQL
Server instance. Gated integration tests against a real DB live in a
separate file and opt in via ``PMD_ENABLE_SQL_INTEGRATION_TESTS=1``
(per spec D8).

Phase 8 (2026-04-24): ``select_all.sql`` was expanded from 7 to 13
columns to join against SITE_PRODUCTION_RUN_HISTORY (shift, weather)
and SITE_PRODUCTION_RUN_COMMENTS (notes). All test row tuples below
were expanded to match.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.integrations.production_report.sql_source import SqlProductionReportSource
from app.integrations.sql.queries import load_query

# -- aioodbc-shaped fakes ---------------------------------------------------
# We only need the slice of aioodbc's surface that SqlProductionReportSource
# actually touches: pool.acquire() -> async CM yielding conn; conn.cursor()
# -> async CM yielding cur; cur.execute / fetchone / fetchall.


class _AsyncCtx:
    """Minimal async context manager yielding a fixed value."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc):
        return False


class FakeCursor:
    def __init__(
        self,
        rows: list[tuple] | None = None,
        *,
        fail_with: Exception | None = None,
    ) -> None:
        self._rows = list(rows or [])
        self._fail_with = fail_with
        self.executed: list[str] = []

    async def execute(self, sql: str, *params) -> None:
        self.executed.append(sql)
        if self._fail_with is not None:
            raise self._fail_with

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _AsyncCtx:
        return _AsyncCtx(self._cursor)


class FakePool:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def acquire(self) -> _AsyncCtx:
        return _AsyncCtx(FakeConnection(self._cursor))


# Column order for select_all.sql (Phase 8). Any test that passes a row
# tuple through the fake cursor uses exactly these 13 columns. Helper
# below builds a tuple with enrichment fields defaulted to None so the
# older tests can keep their focused assertions.
def _row(
    *,
    id=101,
    prod_date=None,
    prod_id="PR_X",
    site_id=101,
    department_id=127,
    payload='{"Metrics":{}}',
    dtm=None,
    shift=None,
    weather_conditions=None,
    avg_temp=None,
    avg_humidity=None,
    max_wind_speed=None,
    notes=None,
):
    if prod_date is None:
        prod_date = datetime(2026, 4, 22)
    return (
        id, prod_date, prod_id, site_id, department_id, payload, dtm,
        shift, weather_conditions, avg_temp, avg_humidity, max_wind_speed, notes,
    )


# -- tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_ok_when_select_one_returns_one() -> None:
    pool = FakePool(FakeCursor(rows=[(1,)]))
    src = SqlProductionReportSource(pool=pool)
    status = await src.ping()
    assert status.ok is True
    assert "returned 1" in status.detail


@pytest.mark.asyncio
async def test_ping_unhealthy_on_unexpected_result() -> None:
    pool = FakePool(FakeCursor(rows=[(999,)]))
    src = SqlProductionReportSource(pool=pool)
    status = await src.ping()
    assert status.ok is False
    assert "Unexpected" in status.detail


@pytest.mark.asyncio
async def test_ping_unhealthy_on_driver_exception() -> None:
    pool = FakePool(FakeCursor(fail_with=RuntimeError("TCP/IP connection failed")))
    src = SqlProductionReportSource(pool=pool)
    status = await src.ping()
    assert status.ok is False
    assert "RuntimeError" in status.detail
    assert "TCP/IP connection failed" in status.detail


@pytest.mark.asyncio
async def test_fetch_rows_casts_ints_to_strings_and_parses_payload() -> None:
    prod_date = datetime(2026, 4, 22, 0, 0)
    dtm = datetime(2026, 4, 22, 15, 41)
    row = _row(
        id=101,
        prod_date=prod_date,
        prod_id="PR101_03_20260422_1_001",
        site_id=101,
        department_id=127,
        payload='{"Metrics":{"Workcenter":{"Availability":99.9}}}',
        dtm=dtm,
    )
    pool = FakePool(FakeCursor(rows=[row]))
    src = SqlProductionReportSource(pool=pool)
    rows = await src.fetch_rows()
    assert len(rows) == 1
    r = rows[0]
    assert r.id == 101
    assert r.prod_date == prod_date
    assert r.prod_id == "PR101_03_20260422_1_001"
    assert r.site_id == "101"
    assert isinstance(r.site_id, str)
    assert r.department_id == "127"
    assert isinstance(r.department_id, str)
    assert r.payload == {"Metrics": {"Workcenter": {"Availability": 99.9}}}
    assert r.dtm == dtm
    # Phase 8 enrichment defaulted to None when not populated.
    assert r.shift is None
    assert r.weather_conditions is None
    assert r.avg_temp is None
    assert r.avg_humidity is None
    assert r.max_wind_speed is None
    assert r.notes is None


@pytest.mark.asyncio
async def test_fetch_rows_handles_null_dtm() -> None:
    row = _row(id=42, prod_id="PR101_X", dtm=None)
    pool = FakePool(FakeCursor(rows=[row]))
    src = SqlProductionReportSource(pool=pool)
    rows = await src.fetch_rows()
    assert rows[0].dtm is None


@pytest.mark.asyncio
async def test_fetch_rows_handles_empty_payload() -> None:
    row = _row(id=1, prod_id="P1", payload="")
    pool = FakePool(FakeCursor(rows=[row]))
    src = SqlProductionReportSource(pool=pool)
    rows = await src.fetch_rows()
    assert rows[0].payload == {}


@pytest.mark.asyncio
async def test_fetch_rows_reads_enrichment_fields() -> None:
    """Phase 8: enrichment columns from the two LEFT JOINs land on the
    dataclass. Numeric columns (avg_temp, avg_humidity, max_wind_speed)
    come back as ``float``; string columns pass through unchanged."""
    row = _row(
        id=201,
        prod_id="PR_ENRICHED",
        shift="Day",
        weather_conditions="Partly Cloudy",
        avg_temp=72.5,
        avg_humidity=58.0,
        max_wind_speed=12.3,
        notes="Belt C3 replaced at 0230; minor dust accumulation on screen 2.",
    )
    pool = FakePool(FakeCursor(rows=[row]))
    src = SqlProductionReportSource(pool=pool)
    rows = await src.fetch_rows()
    r = rows[0]
    assert r.shift == "Day"
    assert r.weather_conditions == "Partly Cloudy"
    assert r.avg_temp == 72.5 and isinstance(r.avg_temp, float)
    assert r.avg_humidity == 58.0 and isinstance(r.avg_humidity, float)
    assert r.max_wind_speed == 12.3 and isinstance(r.max_wind_speed, float)
    assert r.notes.startswith("Belt C3 replaced")


@pytest.mark.asyncio
async def test_fetch_rows_tolerates_null_enrichment_from_left_join_miss() -> None:
    """A production report without a history row (LEFT JOIN misses) gets
    NULL across every enrichment column. The dataclass reports None for
    each, keeping the row usable for all existing code paths."""
    row = _row(
        id=301,
        prod_id="PR_NO_HISTORY",
        shift=None,
        weather_conditions=None,
        avg_temp=None,
        avg_humidity=None,
        max_wind_speed=None,
        notes=None,
    )
    pool = FakePool(FakeCursor(rows=[row]))
    src = SqlProductionReportSource(pool=pool)
    r = (await src.fetch_rows())[0]
    assert r.shift is None
    assert r.weather_conditions is None
    assert r.avg_temp is None
    assert r.avg_humidity is None
    assert r.max_wind_speed is None
    assert r.notes is None


@pytest.mark.asyncio
async def test_list_site_ids_returns_sorted_distinct_strings() -> None:
    r1 = _row(id=1, prod_id="P1", site_id=101, department_id=127)
    r2 = _row(id=2, prod_id="P2", site_id=102, department_id=127)
    r3 = _row(id=3, prod_id="P3", site_id=101, department_id=130)
    pool = FakePool(FakeCursor(rows=[r1, r2, r3]))
    src = SqlProductionReportSource(pool=pool)
    ids = await src.list_site_ids()
    assert ids == ["101", "102"]
    assert all(isinstance(i, str) for i in ids)


def test_load_query_reads_ping_and_select_all() -> None:
    """Smoke-check that the query files bundled alongside the source load."""
    queries_dir = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "integrations"
        / "production_report"
        / "queries"
    )
    ping = load_query(queries_dir, "ping")
    select_all = load_query(queries_dir, "select_all")
    assert "SELECT 1" in ping
    # Phase 8: enriched select joins three tables; all three names must appear.
    assert "FROM [UNS].[SITE_PRODUCTION_RUN_REPORTS]" in select_all
    assert "[UNS].[SITE_PRODUCTION_RUN_HISTORY]" in select_all
    assert "[UNS].[SITE_PRODUCTION_RUN_COMMENTS]" in select_all
    assert "SELECT *" not in select_all
