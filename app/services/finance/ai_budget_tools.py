"""The budget tool: the limits the user set, and spend against them.

Split from ``tools`` when it outgrew its line budget; a limit is a number
the user chose, read nowhere else, so it stands apart from the reads of
what was spent.
"""

from typing import Any

from app.core.db import get_async_session
from app.core.tools import register_tool
from app.services.finance.schemas.agent_tools import Budget, BudgetLine
from app.services.finance.utils import current_period_month


async def budget(period_month: int | None = None) -> Budget:
    """The limits the user actually set, and how the month is going
    against them: 'period_month' (YYYYMM), 'limits' (every FLEXIBLE
    line - 'category' or 'payee', 'limit_cents', 'spent_cents',
    'remaining_cents', and 'status' of good/warn/critical), 'commitments' (the
    recurring bills shown for context, which are NOT limits anyone set),
    and 'stats' (the month's totals, how many limits are over, the days
    left in the period, and what is left: 'left_in_limits_under_budget_cents'
    is what the limits with room still have, 'net_left_cents' that less
    what the others went over - name which one you report).

    Reach for this whenever the question is what something is BUDGETED
    at, what is left, or what is over - "what is our budget for
    Medicine/Drugs?". A limit is a number the user chose and it lives
    nowhere else: `ledger` shows what was SPENT, which is a different
    question and cannot answer this one. ``period_month`` is YYYYMM for
    an earlier month; omitted means the current period. A month that has
    ended reads as it was recorded when it ended (its bills and income
    then, not now), with 'changed_since' saying what was filed into it
    later; one that ended before records were kept is read as it is now.

    Only 'limits' carry a real spend-vs-limit status. A commitment's
    'limit_cents' is just what that bill typically costs, so never report one
    as a budget the user set, or as being over or under.
    """
    from app.services.finance.domains.planning import budgets

    async with get_async_session() as session:
        closed = (
            await budgets.month_as_closed(
                session, owner_user_id=None, period_month=period_month
            )
            if period_month is not None and period_month < current_period_month()
            else None
        )
        if closed is not None:
            summary = closed.summary  # as recorded when it ended (#319)
        else:
            summary = await budgets.budget_summary(
                session, owner_user_id=None, period_month=period_month
            )

    def line(row: Any) -> BudgetLine:
        return {
            "category": row.category_name,
            "category_id": row.category_id,
            "payee": row.payee_label,
            "payee_key": row.payee_key,
            "limit_cents": row.allocated_amount,
            "spent_cents": row.spent_amount,
            # A limit that rolls over carries last months' leftover (or
            # overspending) into this one (#360); what remains counts it.
            "rolls_over": row.rollover,
            "carried_cents": row.carried_amount,
            "remaining_cents": row.available_amount - row.spent_amount,
            "status": row.status,
        }

    limits = [line(row) for row in summary.bucket("flexible").lines]
    commitments = [
        line(row)
        for bucket in summary.buckets
        if bucket.name != "flexible"
        for row in bucket.lines
    ]
    stats = summary.stats
    remaining = [row["remaining_cents"] for row in limits]
    return {
        "period_month": summary.period_month,
        "limits": limits,
        "commitments": commitments,
        "stats": {
            "flexible_spent_cents": stats.flexible_spent,
            "flexible_allocated_cents": stats.flexible_allocated,
            "days_left_in_period": stats.days_left_in_period,
            "over_budget_count": stats.over_budget_count,
            "over_budget_labels": stats.over_budget_labels,
            "fixed_total_cents": stats.fixed_total,
            "left_in_limits_under_budget_cents": sum(r for r in remaining if r > 0),
            "net_left_cents": sum(remaining),
        },
        # Cents, as recorded ("then") and as now, when filed into since.
        "changed_since": closed.changed_since() if closed else None,
    }


register_tool(
    "budget",
    budget,
    description="The limits the user set, and spend against them this period",
    effect="read",
    replace=True,
)
