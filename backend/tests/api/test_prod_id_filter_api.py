"""API tests for the Phase 38 prod_id_filter query param.

Covers the three rollup routes that now honor the PR/PRM selection.
Aggregation math is pinned in tests/services/test_prod_id_filter.py;
here we assert the param is accepted (200 + envelope) and that an
unrecognized value is rejected (422). The Run Report export route is
deliberately excluded -- it takes no prod_id_filter by design.
"""

from __future__ import annotations

import pytest

_ROLLUP_ROUTES = [
    "/api/production-report/rollup/monthly",
    "/api/production-report/circuit-rollup/monthly",
    "/api/production-report/product-rollup/monthly",
]
_WINDOW = {"site_id": "101", "from_date": "2025-05-01", "to_date": "2026-06-30"}


@pytest.mark.parametrize("route", _ROLLUP_ROUTES)
@pytest.mark.parametrize("prod_filter", ["PR", "PRM", "all"])
def test_rollup_accepts_prod_id_filter(client, route: str, prod_filter: str) -> None:
    resp = client.get(route, params={**_WINDOW, "prod_id_filter": prod_filter})
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "101"
    assert body["bucket"] == "monthly"


@pytest.mark.parametrize("route", _ROLLUP_ROUTES)
def test_rollup_rejects_unknown_prod_id_filter(client, route: str) -> None:
    resp = client.get(route, params={**_WINDOW, "prod_id_filter": "PRX"})
    assert resp.status_code == 422


@pytest.mark.parametrize("route", _ROLLUP_ROUTES)
def test_rollup_omitting_prod_id_filter_unchanged(client, route: str) -> None:
    # Backward compatible: no param behaves exactly as before.
    resp = client.get(route, params=_WINDOW)
    assert resp.status_code == 200
