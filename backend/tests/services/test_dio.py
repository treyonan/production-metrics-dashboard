"""Service tests for ``get_dio_daily`` (Spec 005).

Uses a fake source (the live SP can't run in CI) to verify window
validation, the inclusive DATETIME bounds handed to the SP, the day
count, and NULL passthrough for the days-of-supply figures.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.integrations.dio.source import DioRecord
from app.services.dio import get_dio_daily


class _FakeDioSource:
    """Records each (site, start, end) call; returns canned records."""

    name = "fake:dio"

    def __init__(self, records: list[DioRecord]) -> None:
        self._records = records
        self.calls: list[tuple[str, datetime, datetime]] = []

    async def fetch_records(self, *, site_id, start, end):
        self.calls.append((site_id, start, end))
        return list(self._records)


def _rec(code: str = "ST5450", **kw) -> DioRecord:
    base = {
        "item_code": code,
        "item_description": '1 1/2" CRUSHER RUN',
        "total_sales": 1000.0,
        "tpd_sales": 100.0,
        "current_inventory": 500.0,
        "days_on_hand": 5.0,
        "days_after_shutdown": -62.0,
    }
    base.update(kw)
    return DioRecord(**base)


@pytest.mark.asyncio
async def test_passes_inclusive_window_and_counts_days():
    src = _FakeDioSource([_rec()])
    result = await get_dio_daily(
        src, site_id="101", from_date=date(2026, 6, 1), to_date=date(2026, 6, 30)
    )
    assert result.day_count == 30
    assert len(result.records) == 1
    assert len(src.calls) == 1
    site, start, end = src.calls[0]
    assert site == "101"
    assert start == datetime(2026, 6, 1, 0, 0, 0)
    # End-of-day is whole seconds (no microseconds) to avoid the DATETIME
    # round-up that would otherwise inflate the SP's DayCount divisor.
    assert end == datetime(2026, 6, 30, 23, 59, 59)
    assert end.microsecond == 0


@pytest.mark.asyncio
async def test_single_day_window_counts_one_day():
    src = _FakeDioSource([])
    result = await get_dio_daily(
        src, site_id="101", from_date=date(2026, 6, 15), to_date=date(2026, 6, 15)
    )
    assert result.day_count == 1
    assert result.records == []


@pytest.mark.asyncio
async def test_null_days_pass_through():
    src = _FakeDioSource(
        [_rec(total_sales=0.0, days_on_hand=None, days_after_shutdown=None)]
    )
    result = await get_dio_daily(
        src, site_id="101", from_date=date(2026, 6, 1), to_date=date(2026, 6, 7)
    )
    assert result.records[0].days_on_hand is None
    assert result.records[0].days_after_shutdown is None


@pytest.mark.asyncio
async def test_inverted_window_raises():
    src = _FakeDioSource([])
    with pytest.raises(ValueError):
        await get_dio_daily(
            src, site_id="101", from_date=date(2026, 6, 30), to_date=date(2026, 6, 1)
        )
