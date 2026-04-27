"""Tests for /api/sites."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_sites_returns_both_sites_with_names(client: TestClient) -> None:
    resp = client.get("/api/sites")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    ids = {s["id"] for s in body["sites"]}
    assert ids == {"101", "102"}

    by_id = {s["id"]: s for s in body["sites"]}
    # Default settings map 101 -> "Big Canyon Quarry"; 102 -> synthetic demo label.
    assert by_id["101"]["name"] == "Big Canyon Quarry"
    assert "Synthetic" in by_id["102"]["name"]


def test_sites_sorted_by_id(client: TestClient) -> None:
    resp = client.get("/api/sites")
    body = resp.json()
    ids = [s["id"] for s in body["sites"]]
    assert ids == sorted(ids)
