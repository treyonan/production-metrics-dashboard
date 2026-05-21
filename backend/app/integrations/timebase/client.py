"""Timebase i3X REST client + per-site registry.

Each site has its own historian instance on its own plant network, so
the FastAPI service holds a registry of clients keyed by ``site_id``
(strings, matching the rest of the codebase). The lifespan iterates
the loaded catalog at startup, builds one ``TimebaseClient`` per site
from its catalog-declared ``base_url``, opens each, and closes each
on shutdown.

Phase 1 endpoint surface that uses this:

* ``POST /i3x/objects/history`` -- the only data endpoint the dashboard
  needs. Phase 1 forwards the request unmodified.
* ``GET  /i3x/namespaces``      -- cheap reachability ping for
  ``/api/health``; called once per configured site.

Tests use ``httpx.MockTransport`` to intercept calls without network.
Same pattern as ``app.integrations.external.flow_client``.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any

import httpx


class TimebaseClient:
    """Async client for one Timebase historian.

    Construct with the base URL (e.g. ``http://10.44.135.12:8080``);
    do not include the ``/i3x`` prefix -- the client adds it. Call
    :meth:`aopen` at startup and :meth:`aclose` at shutdown. Identified
    by ``site_id`` for log + health attribution.

    ``transport`` is an injection point for tests; in production leave
    it ``None`` and httpx picks the default transport.
    """

    def __init__(
        self,
        *,
        site_id: str,
        base_url: str,
        dataset: str = "",
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._site_id = site_id
        self._base_url = base_url.rstrip("/")
        self._dataset = dataset
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    @property
    def site_id(self) -> str:
        return self._site_id

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def dataset(self) -> str:
        """Dataset prefix used to compose i3X elementIds for this site.

        Empty string when not configured (e.g. tests that construct a
        client without going through the catalog). The /history route
        requires a non-empty dataset; otherwise composing elementIds
        would produce ``':<tag_path>'`` and the upstream would reject.
        """
        return self._dataset

    @property
    def name(self) -> str:
        """Short identifier used in /api/health output, e.g. 'timebase:i3x:101'."""
        return f"timebase:i3x:{self._site_id}"

    async def aopen(self) -> None:
        """Create the underlying httpx client. Call once at startup."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                headers={"Content-Type": "application/json"},
            )

    async def aclose(self) -> None:
        """Close the underlying httpx client. Call once at shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "TimebaseClient.aopen() was not called; httpx client is None"
            )
        return self._client

    async def get_history(
        self,
        *,
        element_ids: list[str],
        start_time: datetime,
        end_time: datetime,
        max_depth: int = 1,
    ) -> dict[str, Any]:
        """Call ``POST /i3x/objects/history`` and return parsed JSON.

        Pass-through semantics: arguments map to i3X request fields
        one-to-one (``elementIds`` / ``startTime`` / ``endTime`` /
        ``maxDepth``); the returned dict is the upstream response
        unchanged. Routes layer on caching and HTTP error -> 502/504
        translation.

        Raises ``httpx.HTTPStatusError`` on non-2xx upstream responses
        and the relevant ``httpx.*`` exception subclass on timeouts /
        connection failures.
        """
        client = self._require_client()
        body = {
            "elementIds": list(element_ids),
            "startTime": _to_iso(start_time),
            "endTime": _to_iso(end_time),
            "maxDepth": max_depth,
        }
        resp = await client.post("/i3x/objects/history", json=body)
        resp.raise_for_status()
        if not resp.content:
            return {}
        parsed = resp.json()
        if not isinstance(parsed, dict):
            raise httpx.HTTPError(
                f"Unexpected i3X response shape: top-level must be "
                f"a JSON object, got {type(parsed).__name__}"
            )
        return parsed

    async def get_namespaces(self) -> list[dict[str, Any]]:
        """Call ``GET /i3x/namespaces``. Used by ``/api/health``.

        Returns the parsed JSON list. Cheap (no request body, server
        returns a small list).
        """
        client = self._require_client()
        resp = await client.get("/i3x/namespaces")
        resp.raise_for_status()
        if not resp.content:
            return []
        parsed = resp.json()
        if not isinstance(parsed, list):
            raise httpx.HTTPError(
                f"Unexpected i3X /namespaces response shape: top-level "
                f"must be a JSON array, got {type(parsed).__name__}"
            )
        return parsed


# ============================================================================
# Per-site registry
# ============================================================================


class TimebaseClientRegistry:
    """Map of ``site_id -> TimebaseClient``.

    Held on ``app.state.timebase_clients``. The lifespan builds one
    ``TimebaseClient`` per site from the loaded catalog at startup and
    registers it here. Routes ask the registry for the right client
    given a ``site_id`` query parameter.

    Iteration order is deterministic (insertion order), matching the
    order sites appear in ``catalog.yaml``.
    """

    def __init__(self) -> None:
        self._clients: dict[str, TimebaseClient] = {}

    def __contains__(self, site_id: str) -> bool:
        return site_id in self._clients

    def __len__(self) -> int:
        return len(self._clients)

    def __iter__(self):
        return iter(self._clients.values())

    def add(self, client: TimebaseClient) -> None:
        self._clients[client.site_id] = client

    def get(self, site_id: str) -> TimebaseClient | None:
        """Return the client for ``site_id`` or None if not registered."""
        return self._clients.get(site_id)

    def site_ids(self) -> list[str]:
        return list(self._clients.keys())

    async def aclose_all(self) -> None:
        """Close every registered client. Safe to call when some
        clients failed to open (they're never added on failure).
        """
        for c in self._clients.values():
            with contextlib.suppress(Exception):  # best-effort shutdown
                await c.aclose()
        self._clients.clear()


# ============================================================================
# Helpers
# ============================================================================


def _to_iso(dt: datetime) -> str:
    """Serialize a datetime to ISO-8601 in UTC.

    i3X examples use millisecond precision with a trailing ``Z``.
    We match that form: ``2026-05-01T06:06:00.796Z``.
    """
    if dt.tzinfo is None:
        # Treat naive datetimes as UTC. Callers in this codebase pass
        # tz-aware values; this is a defense-in-depth fallback.
        ts = dt.isoformat() + "Z"
    else:
        from datetime import UTC

        ts = dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if not ts.endswith("Z"):
            ts = ts + "Z"
    return ts
