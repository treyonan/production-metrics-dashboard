"""Tests for /api/sites."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import _DEFAULT_SITE_NAMES

# Site IDs carried by the CSV test fixture (tests/_fixtures/csv_source.py over
# the committed sample data). 101 is also a configured site; 102 is data-only
# (no _DEFAULT_SITE_NAMES entry) -> resolves to the "Site 102" fallback.
#
# Expectations below derive from _DEFAULT_SITE_NAMES directly rather than
# hard-coding the site list, so commissioning a new site (e.g. adding
# Roosevelt=110) does NOT break these tests -- they assert the union/ordering
# INVARIANTS, not a snapshot of the current site config. (See tasks/lessons.md:
# "Test invariants, not snapshots of operational config".)
_FIXTURE_DATA_SITE_IDS = {"101", "102"}


def test_sites_returns_union_of_configured_and_data(client: TestClient) -> None:
    """The response is the union of configured site_names AND site IDs
    observed in the source's data.

    Configured-but-empty sites (e.g. Ardmore=100 has no fixture rows) still
    appear so the dashboard dropdown can pre-show them before data lands.
    Configured ids resolve to their configured display name; data-only ids
    fall back to "Site <id>".
    """
    resp = client.get("/api/sites")
    assert resp.status_code == 200
    body = resp.json()

    configured = set(_DEFAULT_SITE_NAMES)
    expected_ids = configured | _FIXTURE_DATA_SITE_IDS
    ids = {s["id"] for s in body["sites"]}
    assert ids == expected_ids
    assert body["count"] == len(expected_ids)

    by_id = {s["id"]: s for s in body["sites"]}
    # Configured sites resolve to their configured name (even with no data).
    for sid, name in _DEFAULT_SITE_NAMES.items():
        assert by_id[sid]["name"] == name
    # Data-only ids (in data, not configured) fall back to the generic label.
    for sid in _FIXTURE_DATA_SITE_IDS - configured:
        assert by_id[sid]["name"] == f"Site {sid}"


def test_sites_order_is_configured_first_then_data_only(client: TestClient) -> None:
    """Configured site_names control listing order (sites[0] is the dashboard's
    default no-deep-link site). Data-only ids without a config entry append
    after, so publishing data first can't quietly make a site the default.

    Expected order = _DEFAULT_SITE_NAMES insertion order, then any data-only
    ids (sorted -- the CSV fixture returns its site ids sorted).
    """
    resp = client.get("/api/sites")
    ids = [s["id"] for s in resp.json()["sites"]]

    configured_order = list(_DEFAULT_SITE_NAMES)
    data_only = sorted(_FIXTURE_DATA_SITE_IDS - set(_DEFAULT_SITE_NAMES))
    assert ids == configured_order + data_only
