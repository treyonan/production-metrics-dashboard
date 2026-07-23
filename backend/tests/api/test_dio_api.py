"""API tests for GET /api/dio/daily (Spec 005).

The DIO SQL source (backed by UNS.GET_SITE_DIO_DAILY_RECORDS, which can't
run in CI) is overridden with a fake. The conftest ``client`` fixture
clears all dependency overrides on teardown, so no cleanup is needed.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.api.dependencies import get_dio_source
from app.integrations.dio.source import DioRecord
from app.main import app


class _FakeDioSource:
    async def fetch_records(
        self, *, site_id: str, start: datetime, end: datetime
    ) -> list[DioRecord]:
        return [
            DioRecord(
                item_code="ST5450",
                item_description='1 1/2" CRUSHER RUN',
                total_sales=1000.0,
                tpd_sales=100.0,
                current_inventory=500.0,
                days_on_hand=5.0,
                days_after_shutdown=-62.0,
            ),
            DioRecord(
                item_code="ST7900",
                item_description='10" SURGE',
                total_sales=0.0,
                tpd_sales=0.0,
                current_inventory=200.0,
                days_on_hand=None,
                days_after_shutdown=None,
            ),
        ]


@pytest.fixture
def client_with_dio(client):
    app.dependency_overrides[get_dio_source] = _FakeDioSource
    return client


def test_dio_daily_happy_path(client_with_dio) -> None:
    resp = client_with_dio.get(
        "/api/dio/daily",
        params={"site_id": "101", "from_date": "2026-06-01", "to_date": "2026-06-30"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "101"
    assert body["from_date"] == "2026-06-01"
    assert body["to_date"] == "2026-06-30"
    assert body["day_count"] == 30
    assert "generated_at" in body
    rows = body["rows"]
    assert len(rows) == 2
    assert {
        "item_code",
        "item_description",
        "total_sales",
        "tpd_sales",
        "current_inventory",
        "days_on_hand",
        "days_after_shutdown",
    }.issubset(rows[0].keys())
    assert rows[0]["item_code"] == "ST5450"
    assert rows[0]["days_after_shutdown"] == -62.0
    # NULL days-of-supply (no sales) round-trips as JSON null.
    assert rows[1]["days_on_hand"] is None
    assert rows[1]["days_after_shutdown"] is None


def test_dio_daily_single_day_counts_one(client_with_dio) -> None:
    resp = client_with_dio.get(
        "/api/dio/daily",
        params={"site_id": "101", "from_date": "2026-06-15", "to_date": "2026-06-15"},
    )
    assert resp.status_code == 200
    assert resp.json()["day_count"] == 1


def test_dio_daily_rejects_inverted_window(client_with_dio) -> None:
    resp = client_with_dio.get(
        "/api/dio/daily",
        params={"site_id": "101", "from_date": "2026-06-30", "to_date": "2026-06-01"},
    )
    assert resp.status_code == 422


def test_dio_daily_rejects_oversized_window(client_with_dio) -> None:
    resp = client_with_dio.get(
        "/api/dio/daily",
        params={"site_id": "101", "from_date": "2020-01-01", "to_date": "2026-12-31"},
    )
    assert resp.status_code == 422
