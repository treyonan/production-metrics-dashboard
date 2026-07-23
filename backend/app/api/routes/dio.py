"""/api/dio/* -- operational Days-of-Supply (DIO) records (Spec 005).

Backed by the stored procedure ``UNS.GET_SITE_DIO_DAILY_RECORDS`` via
``DioSource``. One on-demand endpoint: ``GET /api/dio/daily`` returns one
row per item for a site over an inclusive [from_date, to_date] window.
See ``tasks/specs/005-dio-days-of-supply.md``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_dio_source
from app.integrations.dio.source import DioSource
from app.schemas.dio import DioResponse, DioRow
from app.services.dio import get_dio_daily

router = APIRouter()

DioSourceDep = Annotated[DioSource, Depends(get_dio_source)]

# Cap on the DIO window. The SP aggregates sales across the range per
# item; 366 days bounds a request to ~a year, matching the run-report cap.
_MAX_DIO_DAYS = 366


@router.get(
    "/daily",
    response_model=DioResponse,
    summary="Operational Days-of-Supply per item for a site + window",
    description=(
        "Executes UNS.GET_SITE_DIO_DAILY_RECORDS for the site and returns "
        "one row per item: total sales (SUMMED over the window), average "
        "tons/day, current on-hand inventory (latest snapshot in range), "
        "days of supply (inventory / avg daily sales), and days of supply "
        "after a 67-day shutdown. The two days-of-supply figures are null "
        "when the item had no sales in the window. ``from_date`` / "
        "``to_date`` are inclusive of both days. Cap: 366 days. SP failures "
        "surface as 503. See tasks/specs/005-dio-days-of-supply.md."
    ),
)
async def dio_daily(
    dio_source: DioSourceDep,
    site_id: Annotated[str, Query(description="Site to report (required).")],
    from_date: Annotated[date, Query(description="Inclusive window start, YYYY-MM-DD.")],
    to_date: Annotated[date, Query(description="Inclusive window end, YYYY-MM-DD.")],
) -> DioResponse:
    if from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail=(
                f"from_date ({from_date.isoformat()}) must be <= "
                f"to_date ({to_date.isoformat()})."
            ),
        )
    span_days = (to_date - from_date).days + 1
    if span_days > _MAX_DIO_DAYS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Window too large: {span_days} days exceeds the "
                f"{_MAX_DIO_DAYS}-day cap. Narrow the window."
            ),
        )

    try:
        result = await get_dio_daily(
            dio_source,
            site_id=site_id,
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 -- SP/SQL failure -> graceful 503
        raise HTTPException(
            status_code=503,
            detail={
                "source": "site_dio_daily_records",
                "error": f"{type(exc).__name__}: {exc}",
            },
        ) from exc

    return DioResponse(
        site_id=result.site_id,
        from_date=result.from_date,
        to_date=result.to_date,
        day_count=result.day_count,
        generated_at=datetime.now(UTC),
        rows=[
            DioRow(
                item_code=r.item_code,
                item_description=r.item_description,
                total_sales=r.total_sales,
                tpd_sales=r.tpd_sales,
                current_inventory=r.current_inventory,
                days_on_hand=r.days_on_hand,
                days_after_shutdown=r.days_after_shutdown,
            )
            for r in result.records
        ],
    )
