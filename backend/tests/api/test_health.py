"""Tests for /api/health."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok_with_csv_source(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["environment"] == "local"
    assert isinstance(body["version"], str) and body["version"]
    assert len(body["sources"]) == 1
    src = body["sources"][0]
    assert src["name"] == "csv:production_report"
    assert src["ok"] is True
    assert "readable" in src["detail"]


def test_health_echoes_correlation_id(client: TestClient) -> None:
    cid = "test-correlation-id-abc123"
    resp = client.get("/api/health", headers={"X-Correlation-ID": cid})
    assert resp.status_code == 200
    assert resp.headers.get("X-Correlation-ID") == cid


def test_health_generates_correlation_id_when_absent(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    # Any non-empty string — we don't care about the exact UUID shape here.
    assert resp.headers.get("X-Correlation-ID")
