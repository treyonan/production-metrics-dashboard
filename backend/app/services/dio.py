"""DIO / Days-of-Supply service (Spec 005).

Thin orchestration over ``DioSource``: validate the window, translate the
inclusive [from_date, to_date] day range into the SP's DATETIME bounds,
and hand back typed records plus the window's day count.

Mirrors the shape of ``get_configured_run_report`` (validate -> call
SP-backed source -> typed result). No aggregation here: the SP already
does the per-item math; v1 renders its output verbatim (spec 005 s4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from app.integrations.dio.source import DioRecord, DioSource


@dataclass(frozen=True)
class DioResult:
    """Service-internal DIO result for one (site, window)."""

    site_id: str
    from_date: date
    to_date: date
    day_count: int
    records: list[DioRecord]


# End-of-day time for the SP's inclusive window. Deliberately whole
# seconds (no microseconds): a DATETIME param of 23:59:59.999999 rounds
# UP to the next midnight in SQL Server, which would both pull the next
# day's rows and inflate the SP's DATEDIFF-based DayCount (the divisor for
# TPD / Days-of-Supply). 23:59:59 keeps the window and day count exact.
_END_OF_DAY = time(23, 59, 59)


async def get_dio_daily(
    source: DioSource,
    *,
    site_id: str,
    from_date: date,
    to_date: date,
) -> DioResult:
    """Fetch Days-of-Supply records for a site over an inclusive window.

    The SP window is inclusive: start at 00:00:00 of ``from_date``, end at
    23:59:59 of ``to_date``. ``day_count`` mirrors the SP's own
    ``DATEDIFF(DAY, start, end) + 1`` so the displayed "N days in range"
    matches the divisor the SP used for TPD.

    Raises ``ValueError`` if ``from_date > to_date``.
    """
    if from_date > to_date:
        raise ValueError(
            f"from_date ({from_date.isoformat()}) must be <= "
            f"to_date ({to_date.isoformat()})."
        )

    start_dt = datetime.combine(from_date, time.min)
    end_dt = datetime.combine(to_date, _END_OF_DAY)
    records = await source.fetch_records(site_id=site_id, start=start_dt, end=end_dt)
    day_count = (to_date - from_date).days + 1
    return DioResult(
        site_id=site_id,
        from_date=from_date,
        to_date=to_date,
        day_count=day_count,
        records=records,
    )
