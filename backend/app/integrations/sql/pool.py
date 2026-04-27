"""aioodbc connection-pool helpers.

Thin wrapper around ``aioodbc.create_pool`` so integration code doesn't
depend on the driver module directly. Keeps the default pool sizing in
one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aioodbc

# Default pool sizing. Dashboard polling is low-concurrency; these
# numbers are generous for a single-worker uvicorn. Revisit if
# concurrent viewers grow or background refresh is added.
DEFAULT_MIN_SIZE = 1
DEFAULT_MAX_SIZE = 4


async def create_pool(
    dsn: str,
    *,
    minsize: int = DEFAULT_MIN_SIZE,
    maxsize: int = DEFAULT_MAX_SIZE,
) -> aioodbc.Pool:
    """Create an aioodbc pool against ``dsn``.

    Imports aioodbc lazily so import-time failures don't blow up the
    whole app when the SQL backend isn't actually configured.
    """
    import aioodbc  # local import: optional runtime dep

    return await aioodbc.create_pool(dsn=dsn, minsize=minsize, maxsize=maxsize)
