"""Unit tests for FlowClient.

Uses ``httpx.MockTransport`` so tests run without network. Covers
URL substitution, bearer auth, response parsing, error propagation,
and truncation detection.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.integrations.external.flow_client import (
    FlowClient,
    format_flow_iso,
    parse_url_limit,
    substitute_period,
)


# ---- Pure-function helpers ----


def test_format_flow_iso_millisecond_form() -> None:
    dt = datetime(2026, 4, 1, 12, 30, 45, 123456, tzinfo=UTC)
    assert format_flow_iso(dt) == "2026-04-01T12:30:45.123Z"


def test_substitute_period_replaces_both_placeholders() -> None:
    template = "http://x/api?start=[PeriodStart]&end=[PeriodEnd]&id=1"
    assert (
        substitute_period(template, "2026-04-01T00:00:00.000Z", "2026-04-02T00:00:00.000Z")
        == "http://x/api?start=2026-04-01T00:00:00.000Z&end=2026-04-02T00:00:00.000Z&id=1"
    )


def test_parse_url_limit_finds_query_param() -> None:
    assert parse_url_limit("http://x/api?id=1&limit=1000") == 1000
    assert parse_url_limit("http://x/api?limit=500&id=1") == 500
    assert parse_url_limit("http://x/api?id=1") is None


# ---- FlowClient end-to-end via MockTransport ----


def _make_response(json_body: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=json_body)


@pytest.mark.asyncio
async def test_fetch_history_sends_bearer_and_substitutes_url() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers.get("Content-Type")
        return _make_response(
            {
                "values": [
                    {
                        "id": 1644,
                        "name": "C4.Total",
                        "tags": {"interval": "hourly"},
                        "data": [
                            {
                                "start": "2026-04-01T00:00:00.000Z",
                                "end": "2026-04-01T01:00:00.000Z",
                                "value": 12.5,
                                "detail": {"quality": {"value": 192}},
                            }
                        ],
                    }
                ],
                "errors": [],
            }
        )

    client = FlowClient(api_key="test-key", transport=httpx.MockTransport(handler))
    await client.aopen()
    try:
        url_template = (
            "http://flow/api/v1/data/measures"
            "?start=[PeriodStart]&end=[PeriodEnd]&id=1644&limit=1000"
        )
        start = datetime(2026, 4, 1, tzinfo=UTC)
        end = datetime(2026, 4, 2, tzinfo=UTC)
        result = await client.fetch_history(url_template, start=start, end=end)
    finally:
        await client.aclose()

    # Auth header is "Bearer <key>"
    assert captured["auth"] == "Bearer test-key"
    assert captured["content_type"] == "application/json"
    # Placeholders replaced with the millisecond-UTC strings
    assert "start=2026-04-01T00:00:00.000Z" in captured["url"]
    assert "end=2026-04-02T00:00:00.000Z" in captured["url"]
    # Response parsed: one bucket
    assert len(result.raw_data) == 1
    assert result.raw_data[0]["value"] == 12.5
    # Truncation flag: 1 row but limit=1000 -> not truncated
    assert result.hit_limit is False


@pytest.mark.asyncio
async def test_fetch_history_raises_on_non_2xx() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = FlowClient(api_key="bad-key", transport=httpx.MockTransport(handler))
    await client.aopen()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.fetch_history(
                "http://flow/api?start=[PeriodStart]&end=[PeriodEnd]",
                start=datetime(2026, 4, 1, tzinfo=UTC),
                end=datetime(2026, 4, 2, tzinfo=UTC),
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_fetch_history_detects_truncation_at_limit() -> None:
    """When the response returns exactly limit rows, hit_limit is True."""

    def handler(_request: httpx.Request) -> httpx.Response:
        # 3 rows, limit=3 -> hit_limit True.
        return _make_response(
            {
                "values": [
                    {
                        "id": 1,
                        "data": [
                            {
                                "start": "2026-04-01T00:00:00.000Z",
                                "end": "2026-04-01T01:00:00.000Z",
                                "value": i,
                                "detail": {"quality": {"value": 192}},
                            }
                            for i in range(3)
                        ],
                    }
                ]
            }
        )

    client = FlowClient(api_key="k", transport=httpx.MockTransport(handler))
    await client.aopen()
    try:
        result = await client.fetch_history(
            "http://flow/api?limit=3&start=[PeriodStart]&end=[PeriodEnd]",
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 2, tzinfo=UTC),
        )
    finally:
        await client.aclose()

    assert len(result.raw_data) == 3
    assert result.hit_limit is True


@pytest.mark.asyncio
async def test_fetch_history_handles_empty_values() -> None:
    """Flow returns {values: []} when no measure data exists."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return _make_response({"values": [], "errors": []})

    client = FlowClient(api_key="k", transport=httpx.MockTransport(handler))
    await client.aopen()
    try:
        result = await client.fetch_history(
            "http://flow/api?start=[PeriodStart]&end=[PeriodEnd]&limit=1000",
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 2, tzinfo=UTC),
        )
    finally:
        await client.aclose()

    assert result.raw_data == []
    assert result.hit_limit is False


@pytest.mark.asyncio
async def test_fetch_history_raises_when_aopen_not_called() -> None:
    client = FlowClient(api_key="k")
    with pytest.raises(RuntimeError, match="aopen"):
        await client.fetch_history(
            "http://flow/api?start=[PeriodStart]&end=[PeriodEnd]",
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 2, tzinfo=UTC),
        )
