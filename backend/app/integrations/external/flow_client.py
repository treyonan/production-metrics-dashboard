"""Flow Software REST API client.

Async httpx wrapper around the Flow ``GET /api/v1/data/measures``
endpoint. Used by ``SqlIntervalMetricSource`` to fetch per-tag history
given a URL pulled from ``[FLOW].[INTERVAL_METRIC_TAGS].history_url``.

Auth is a static bearer token: ``FLOW_API_KEY`` from ``backend/.env``
is the API key string directly, no exchange / refresh. Mirrors the
existing Ignition example client (see ``examples/flow-api/client.py``)
which does ``Authorization: Bearer <api_key>``.

URL substitution is literal ``str.replace`` of ``[PeriodStart]`` and
``[PeriodEnd]`` placeholders with ISO-8601 millisecond UTC strings.
The placeholders aren't URL-special and the timestamp form is what
Flow's API doc calls for.

Pagination: Flow URLs include ``limit=1000`` in their query string
(set when the metric is provisioned in Flow). We don't override it.
The caller (this client's ``fetch_points`` consumer) detects
"exactly limit returned" and surfaces a ``truncated`` flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

# Format Flow's docs name: 'YYYY-MM-DDTHH:mm:ss.mmmZ' (millisecond UTC).
_ISO_MS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def format_flow_iso(dt: datetime) -> str:
    """Return ISO-8601 millisecond UTC string for the Flow API.

    Flow expects e.g. ``'2026-04-01T00:00:00.000Z'``. ``%f`` gives
    microseconds (6 digits); we trim to milliseconds (3) to match.
    Caller is responsible for passing a UTC datetime (this function
    doesn't convert).
    """
    return dt.strftime(_ISO_MS_FMT)[:-4] + "Z"


def substitute_period(url_template: str, start: str, end: str) -> str:
    """Replace ``[PeriodStart]`` / ``[PeriodEnd]`` placeholders.

    Literal string replacement; the bracket placeholders aren't
    URL-special so no escaping needed.
    """
    return url_template.replace("[PeriodStart]", start).replace("[PeriodEnd]", end)


_LIMIT_RE = re.compile(r"[?&]limit=(\d+)(?:&|$)")


def parse_url_limit(url: str) -> int | None:
    """Extract the ``limit=N`` value from a Flow URL, if present."""
    match = _LIMIT_RE.search(url)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class FlowFetchResult:
    """One per-tag fetch result.

    ``raw_data`` is the inner ``values[0]['data']`` list from Flow's
    response -- the flat list of bucket dicts. ``hit_limit`` is True
    when the response returned exactly the URL's ``limit=`` value,
    indicating possible truncation.
    """

    raw_data: list[dict[str, Any]]
    hit_limit: bool


class FlowClient:
    """Async client for Flow's measure-history REST endpoint.

    Lifetime: one instance per app, created in lifespan and closed
    on shutdown. Single ``httpx.AsyncClient`` underneath so connection
    pooling works across requests.
    """

    name = "flow:api"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Build a Flow API client.

        ``transport`` is an injection point for tests -- pass an
        ``httpx.MockTransport`` to intercept HTTP calls without
        hitting the network. In production, leave it None and
        httpx uses its default transport.
        """
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def aopen(self) -> None:
        """Create the underlying httpx client. Call once at startup."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            )

    async def aclose(self) -> None:
        """Close the underlying httpx client. Call once at shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": "application/json",
        }

    async def fetch_history(
        self,
        url_template: str,
        *,
        start: datetime,
        end: datetime,
    ) -> FlowFetchResult:
        """Fetch one tag's history.

        Substitutes the placeholders in ``url_template`` with the
        Flow-formatted ISO strings, GETs with bearer auth, raises on
        non-2xx, and returns the inner ``values[0]['data']`` list
        plus a hit-limit flag.

        Returns an empty list (not None) when Flow's response has no
        values for this tag -- consumers can iterate without a None
        check.
        """
        if self._client is None:
            raise RuntimeError(
                "FlowClient.aopen() was not called; httpx client is None"
            )

        url = substitute_period(
            url_template,
            format_flow_iso(start),
            format_flow_iso(end),
        )

        resp = await self._client.get(url, headers=self._headers)
        resp.raise_for_status()

        if not resp.content:
            return FlowFetchResult(raw_data=[], hit_limit=False)
        body = resp.json()

        # Flow shape: { values: [ { data: [...], id, name, tags } ], errors: [] }
        # We requested exactly one ``id`` per URL, so values has at most one entry.
        values = body.get("values") or []
        data = values[0].get("data", []) if values else []

        # Truncation detection: did we hit the URL's baked-in limit?
        url_limit = parse_url_limit(url)
        hit_limit = url_limit is not None and len(data) >= url_limit

        return FlowFetchResult(raw_data=data, hit_limit=hit_limit)
