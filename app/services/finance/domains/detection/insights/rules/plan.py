"""The plan checks itself (#354): actual against the path it saved.

A projection nobody compares with what happened is a picture. Once a
quarter (``finance_plan_check_job``, not the nightly rules: a plan does
not move by the day, and a rule that reads it every night for every
owner is a query nobody asked for), the net worth on the books is read
against where the saved path said it would be by now, and an Attention
item says on track, or by how much off, with the month's saving beside
what the plan assumed.
"""

from __future__ import annotations

from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection.insights.formatting import format_usd
from app.services.finance.domains.detection.insights.rules.shared import (
    create_insight_if_new,
)
from app.services.finance.domains.planning import plan as plans
from app.services.shared.queries import stored_owner

PLAN_CHECK = "plan_check"


def quarter_key(today: date) -> str:
    return f"{today.year}Q{(today.month - 1) // 3 + 1}"


async def plan_check(
    db: AsyncSession,
    owner_user_id: int | None,
    today: date,
    row: plans.FinancePlan | None = None,
) -> int:
    """Where the household stands against its saved plan, filed once a
    quarter (the dedup key). Silent until a plan has been saved: there is
    no path to be off. The number of items created."""
    store_owner = stored_owner(owner_user_id)
    check = await plans.check_plan(
        db, owner_user_id=owner_user_id, today=today, row=row
    )
    if check is None:
        return 0
    if check.on_track:
        severity, title = "info", "The plan is on track"
    elif check.gap < 0:
        severity, title = "warning", f"Behind the plan by {format_usd(check.gap)}"
    else:
        severity, title = "info", f"Ahead of the plan by {format_usd(check.gap)}"
    body = (
        f"Net worth is {format_usd(check.actual)} against "
        f"{format_usd(check.expected)} on the plan's path. Saving "
        f"{format_usd(check.saving)} a month into investments against "
        f"{format_usd(check.planned_saving)} planned."
    )
    if await create_insight_if_new(
        db,
        owner_user_id=store_owner,
        insight_type=PLAN_CHECK,
        dedup_key=f"{PLAN_CHECK}:{quarter_key(today)}",
        severity=severity,
        title=title,
        body=body,
        detected_amount=check.gap,
        period_end=today,
    ):
        return 1
    return 0
