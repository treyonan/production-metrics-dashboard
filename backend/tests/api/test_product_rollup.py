"""API tests for GET /api/production-report/product-rollup/{bucket} (Phase 37).

Uses the conftest CSV fixture source. The sample data may carry no
Produced_Metrics with Display_Chart on, so the happy path asserts the
envelope shape (aggregation math is covered in the service tests);
validation paths assert the 422 caps.
"""

from __future__ import annotations


def test_product_rollup_envelope_shape(client) -> None:
    resp = client.get(
        "/api/production-report/product-rollup/monthly",
        params={"site_id": "101", "from_date": "2025-05-01", "to_date": "2026-06-30"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "101"
    assert body["bucket"] == "monthly"
    assert body["from_date"] == "2025-05-01"
    assert isinstance(body["departments"], list)


def test_product_rollup_rejects_inverted_window(client) -> None:
    resp = client.get(
        "/api/production-report/product-rollup/monthly",
        params={"site_id": "101", "from_date": "2026-06-01", "to_date": "2026-01-31"},
    )
    assert resp.status_code == 422


def test_product_rollup_rejects_oversized_window(client) -> None:
    resp = client.get(
        "/api/production-report/product-rollup/monthly",
        params={"site_id": "101", "from_date": "2020-01-01", "to_date": "2026-12-31"},
    )
    assert resp.status_code == 422


def test_product_rollup_rejects_bad_bucket(client) -> None:
    resp = client.get(
        "/api/production-report/product-rollup/weekly",
        params={"site_id": "101", "from_date": "2026-01-01", "to_date": "2026-04-30"},
    )
    assert resp.status_code == 422
