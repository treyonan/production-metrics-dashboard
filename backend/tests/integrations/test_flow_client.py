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

    client = FlowClient(default_api_key="test-key", transport=httpx.MockTransport(handler))
    await client.aopen()
    try:
        url_template = (
            "http://flow/api/v1/data/measures"
            "?start=[PeriodStart]&end=[PeriodEnd]&id=1644&limit=1000"
        )
        start = datetime(2026, 4, 1, tzinfo=UTC)
        end = datetime(2026, 4, 2, tzinfo=UTC)
        result = await client.fetch_history(
            url_template, start=start, end=end, site_id="101"
        )
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

    client = FlowClient(default_api_key="bad-key", transport=httpx.MockTransport(handler))
    await client.aopen()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.fetch_history(
                "http://flow/api?start=[PeriodStart]&end=[PeriodEnd]",
                start=datetime(2026, 4, 1, tzinfo=UTC),
                end=datetime(2026, 4, 2, tzinfo=UTC),
                site_id="101",
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

    client = FlowClient(default_api_key="k", transport=httpx.MockTransport(handler))
    await client.aopen()
    try:
        result = await client.fetch_history(
            "http://flow/api?limit=3&start=[PeriodStart]&end=[PeriodEnd]",
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 2, tzinfo=UTC),
            site_id="101",
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

    client = FlowClient(default_api_key="k", transport=httpx.MockTransport(handler))
    await client.aopen()
    try:
        result = await client.fetch_history(
            "http://flow/api?start=[PeriodStart]&end=[PeriodEnd]&limit=1000",
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 2, tzinfo=UTC),
            site_id="101",
        )
    finally:
        await client.aclose()

    assert result.raw_data == []
    assert result.hit_limit is False


@pytest.mark.asyncio
async def test_fetch_history_raises_when_aopen_not_called() -> None:
    client = FlowClient(default_api_key="k")
    with pytest.raises(RuntimeError, match="aopen"):
        await client.fetch_history(
            "http://flow/api?start=[PeriodStart]&end=[PeriodEnd]",
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 2, tzinfo=UTC),
            site_id="101",
        )


# ============================================================================
# Per-site auth (Phase 27.1, 2026-06-03)
# ============================================================================
#
# Each Flow installation has its own bearer token. The client holds a
# dict keyed by site_id and falls back to a default for any site not in
# the dict. These tests pin both branches of the resolver.


@pytest.mark.asyncio
async def test_fetch_history_sends_per_site_key_when_configured() -> None:
    """site_id has its own per-site token -> that token is sent."""
    seen_auths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auths.append(request.headers.get("authorization", ""))
        return _make_response({"values": []})

    client = FlowClient(
        api_keys={"101": "bcq-token", "100": "arq-token"},
        default_api_key="default-token",
        transport=httpx.MockTransport(handler),
    )
    await client.aopen()
    try:
        await client.fetch_history(
            "http://dbp-bcq:4501/api?start=[PeriodStart]&end=[PeriodEnd]",
            start=datetime(2026, 6, 1, tzinfo=UTC),
            end=datetime(2026, 6, 2, tzinfo=UTC),
            site_id="101",
        )
        await client.fetch_history(
            "http://dbp-arq:4501/api?start=[PeriodStart]&end=[PeriodEnd]",
            start=datetime(2026, 6, 1, tzinfo=UTC),
            end=datetime(2026, 6, 2, tzinfo=UTC),
            site_id="100",
        )
    finally:
        await client.aclose()

    assert seen_auths == ["Bearer bcq-token", "Bearer arq-token"]


@pytest.mark.asyncio
async def test_fetch_history_falls_back_to_default_key() -> None:
    """site_id without a per-site entry -> default_api_key is used."""
    seen_auth = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth["v"] = request.headers.get("authorization", "")
        return _make_response({"values": []})

    client = FlowClient(
        api_keys={"101": "bcq-token"},  # 100 deliberately absent
        default_api_key="default-token",
        transport=httpx.MockTransport(handler),
    )
    await client.aopen()
    try:
        await client.fetch_history(
            "http://flow/api?start=[PeriodStart]&end=[PeriodEnd]",
            start=datetime(2026, 6, 1, tzinfo=UTC),
            end=datetime(2026, 6, 2, tzinfo=UTC),
            site_id="100",
        )
    finally:
        await client.aclose()

    assert seen_auth["v"] == "Bearer default-token"


@pytest.mark.asyncio
async def test_fetch_history_raises_when_no_key_for_site() -> None:
    """No per-site key + no default for that site -> RuntimeError before HTTP."""
    client = FlowClient(
        api_keys={"101": "bcq-token"},  # only 101 configured
        default_api_key=None,            # no fallback
    )
    await client.aopen()
    try:
        with pytest.raises(RuntimeError, match="No Flow API key configured"):
            await client.fetch_history(
                "http://flow/api?start=[PeriodStart]&end=[PeriodEnd]",
                start=datetime(2026, 6, 1, tzinfo=UTC),
                end=datetime(2026, 6, 2, tzinfo=UTC),
                site_id="100",   # not in api_keys, no default
            )
    finally:
        await client.aclose()
