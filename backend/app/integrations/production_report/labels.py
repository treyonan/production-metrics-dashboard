"""Chart label lookup.

The dashboard renders calcs lines such as ``Total = C1+C8-C7``. The
left-hand label was the raw metric key (``Total``, ``Rate``, ``Yield``,
``Performance``, ``Availability``); we now resolve it to a human-readable
display name from the existing ``[IA_ENTERPRISE].[MES].[RUN_REPORTS_CONFIG]``
table family (the same three tables that drive the legacy
``[UNS].[GET_CONFIGURED_RUN_REPORT]`` flat-report SP).

Resolution model
----------------

The lookup key is a five-tuple:

    (site_id, department_id, class, asset, column_name)

mirroring how a ``Calcs`` entry's JSON path decomposes:

    Workcenter.Calcs.<m>                    -> (site, dept, 'Workcenter', 'Workcenter', m)
    Circuit.<cid>.Calcs.<m>                 -> (site, dept, 'Circuit', cid, m)
    Circuit.<cid>.Line.A.Calcs.<m>          -> (site, dept, 'Circuit_Line_A', cid, m)
    Circuit.<cid>.Line.B.Calcs.<m>          -> (site, dept, 'Circuit_Line_B', cid, m)
    Circuit.<cid>.Line.C.Calcs.<m>          -> (site, dept, 'Circuit_Line_C', cid, m)

Resolution walks most-specific to least-specific:

    1. (site_id, department_id, class, asset, column_name)   -- per-(site, dept) row
    2. (0,       0,             class, asset, column_name)   -- global fallback row
    3. column_name                                            -- raw metric key

Step 3 is the safety net: an empty table or a missing row still produces
a sane chart, identical to the pre-config behaviour. Rolling out new
labels can therefore happen by INSERT alone, no API change required.

Caching
-------

The label set is small (low hundreds of rows at most) and changes
rarely, so we load it once at startup and refresh on a fixed TTL.
Calls into :func:`ChartLabels.resolve` are pure dict lookups -- there's
no per-request SQL round trip.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from app.core.logging import get_logger
from app.integrations.sql.queries import load_query

if TYPE_CHECKING:
    import aioodbc

_QUERIES_DIR = Path(__file__).parent / "queries"
_log = get_logger("app.integrations.production_report.labels")

# How long a loaded label set remains "fresh" before the caller is
# expected to ask the source to reload. Aligned with the other in-process
# caches in the API (~5 min). Calls into resolve() are unaffected --
# this only governs background refreshes.
LABEL_CACHE_TTL_SECONDS: Final[int] = 300

# Type alias for the cache key. Site/dept are ints to match the SQL
# column types and the (0, 0) sentinel; class/asset/column_name are
# strings sourced verbatim from the join.
LabelKey = tuple[int, int, str, str, str]

# Sentinel value used in RUN_REPORTS_CONFIG.SITE_ID / DEPARTMENT_ID to
# mark a row as a global fallback. The chart-label consumer treats
# rows with both columns equal to this value as "applies to every
# (site, dept) that doesn't have a specific row for the same
# (class, asset, column_name) tuple."
GLOBAL_SENTINEL: Final[int] = 0


@dataclass(frozen=True, slots=True)
class ChartLabels:
    """Immutable view of the chart-label lookup table.

    Built once per refresh by :meth:`SqlChartLabelSource.load`. Callers
    hold a reference and call :meth:`resolve` per chart panel.
    """

    by_key: dict[LabelKey, str] = field(default_factory=dict)
    # Monotonic timestamp of when the data was loaded -- used by the
    # owning service to decide when to refresh. Not exposed in the
    # response payload.
    loaded_at: float = 0.0
    row_count: int = 0

    def resolve(
        self,
        site_id: int,
        department_id: int,
        class_name: str,
        asset: str,
        column_name: str,
    ) -> str:
        """Return the configured display label, or the raw metric key.

        Most-specific to least-specific lookup with a graceful fallback
        to ``column_name`` so charts always have *some* title even if
        the config table is empty or partially populated.
        """
        for site, dept in (
            (site_id, department_id),
            (GLOBAL_SENTINEL, GLOBAL_SENTINEL),
        ):
            v = self.by_key.get((site, dept, class_name, asset, column_name))
            if v is not None:
                return v
        return column_name


class SqlChartLabelSource:
    """Loads chart labels from SQL Server via aioodbc.

    One instance per app lifespan. The service layer holds the
    :class:`ChartLabels` snapshot and refreshes it on the configured
    TTL. Failures during a refresh log a warning but keep the previous
    snapshot in place so chart rendering never blanks out due to a
    transient SQL hiccup.
    """

    name = "sql:chart_labels"

    def __init__(self, pool: aioodbc.Pool) -> None:
        self._pool = pool
        # Load query string at construction time so a missing/renamed
        # .sql file fails fast at import rather than during the first
        # refresh.
        self._select_sql = load_query(_QUERIES_DIR, "select_chart_labels")

    async def load(self) -> ChartLabels:
        """Read every active label row and return a fresh snapshot."""
        async with (
            self._pool.acquire() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(self._select_sql)
            _DESC = cur.description  # snapshot for column-name lookup
            rows = await cur.fetchall()

        # Resolve column positions from the cursor description rather than
        # hard-coding indices. The select_chart_labels.sql query can grow
        # or reorder columns without breaking this loader as long as the
        # six aliases below are still present in the SELECT list.
        by_key: dict[LabelKey, str] = {}
        if rows:
            # Build a lookup from alias -> position. Aliases come from the
            # SQL "AS <alias>" clauses; pyodbc lowercases them in
            # cursor.description on most drivers but we lowercase
            # defensively in case the driver returns them mixed-case.
            cols = {d[0].lower(): i for i, d in enumerate(_DESC) }
            try:
                i_site   = cols["site_id"]
                i_dept   = cols["department_id"]
                i_class  = cols["class"]
                i_asset  = cols["asset"]
                i_metric = cols["column_name"]
                i_label  = cols["display_name"]
            except KeyError as exc:
                raise RuntimeError(
                    f"select_chart_labels.sql missing required column "
                    f"alias: {exc!s}. Expected: site_id, department_id, "
                    f"class, asset, column_name, display_name."
                ) from exc
            for r in rows:
                site_id      = int(r[i_site])
                department_id = int(r[i_dept])
                class_name   = str(r[i_class])
                asset_val    = r[i_asset]
                asset        = str(asset_val) if asset_val is not None else ""
                column_name  = str(r[i_metric])
                display_name = str(r[i_label])
                by_key[(site_id, department_id, class_name, asset, column_name)] = (
                    display_name
                )

        _log.info(
            "chart_labels.loaded",
            row_count=len(by_key),
            globals=sum(
                1 for (s, d, *_rest) in by_key
                if s == GLOBAL_SENTINEL and d == GLOBAL_SENTINEL
            ),
        )
        return ChartLabels(
            by_key=by_key,
            loaded_at=time.monotonic(),
            row_count=len(by_key),
        )


# --- Path-to-key helpers -----------------------------------------------------
# Tiny pure functions so the service layer (and tests) can build a
# LabelKey from the natural JSON path of a Calcs entry without
# re-implementing the mapping at every call site.


def workcenter_key(
    site_id: int, department_id: int, metric_key: str
) -> LabelKey:
    """``Workcenter.Calcs.<metric>`` -> lookup key."""
    return (site_id, department_id, "Workcenter", "Workcenter", metric_key)


def circuit_key(
    site_id: int, department_id: int, circuit_id: str, metric_key: str
) -> LabelKey:
    """``Circuit.<cid>.Calcs.<metric>`` -> lookup key."""
    return (site_id, department_id, "Circuit", circuit_id, metric_key)


def line_key(
    site_id: int,
    department_id: int,
    circuit_id: str,
    line_id: str,
    metric_key: str,
) -> LabelKey:
    """``Circuit.<cid>.Line.<lid>.Calcs.<metric>`` -> lookup key.

    The schema models line position via a per-letter CLASS row
    (``Circuit_Line_A`` / ``_B`` / ``_C``), with ASSET carrying the
    parent circuit id. Mirrors the case-when in the legacy SP.
    """
    return (
        site_id,
        department_id,
        f"Circuit_Line_{line_id}",
        circuit_id,
        metric_key,
    )
