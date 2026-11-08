"""Debts that pay down (#347-#350): the terms on file, read forward.

The cover's "Paying it down" card said how a lender treats extra money
and nothing about what the loan would do with it; the portfolio listed
every debt and ranked none. Both answers come from one place,
``planning.debts``, so the cover's schedule and the Paying down page's
plan cannot disagree about a month.

The cover takes ``extra`` and ``lump`` on its own URL (pattern 3): the
form re-asks the same page and swaps the one card, so the arithmetic in
the card is the arithmetic the page was built from.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from app.components.web_frontend.filters import money
from app.components.web_frontend.nav import account_cover
from app.components.web_frontend.rendering import render
from app.components.web_frontend.routes.finance.accounts import PAYOFF, _accounts
from app.services.finance.deps import get_finance_service, get_owner_user_id
from app.services.finance.schemas import AccountResponse
from app.services.finance.service import (
    PAYOFF_METHODS,
    Debt,
    FinanceService,
    amortize,
    extra_buys,
    format_apr,
    payoff_plan,
)
from app.services.finance.utils import current_date, money_to_cents

router = APIRouter()
DEFAULT_METHOD = "avalanche"

SCHEDULE_COLUMNS = (
    {"key": "month", "label": "Month"},
    {"key": "interest", "label": "Interest", "kind": "money", "align": "right"},
    {"key": "principal", "label": "Principal", "kind": "money", "align": "right"},
    {"key": "owed", "label": "Owed", "kind": "money", "align": "right"},
)
PLAN_COLUMNS = (
    {"key": "order", "label": "#", "align": "right"},
    {"key": "debt", "label": "Debt", "kind": "page"},
    {"key": "owed", "label": "Owed", "kind": "money", "align": "right"},
    {"key": "rate", "label": "Rate", "align": "right"},
    {"key": "payment", "label": "Payment", "kind": "money", "align": "right"},
    {"key": "paid_off", "label": "Paid off"},
    {"key": "interest", "label": "Interest", "kind": "money", "align": "right"},
)


def _month(day: date | None) -> str:
    return f"{day:%b %Y}" if day else "Never"


def _cents(raw: str) -> int:
    """What was typed in the extra box, as cents; nonsense is nothing."""
    return max(0, money_to_cents(raw) or 0)


def payoff_context(
    account: AccountResponse, *, extra: str = "", lump: str = ""
) -> dict[str, Any]:
    """What the cover's "Paying it down" card draws for a debt: the
    schedule as the terms stand, moved by ``extra`` a month and ``lump``
    now when either was typed, and what that buys."""
    debt = Debt.of(account, account.liability)
    if debt is None:
        return {}
    today = current_date()
    more, lump_sum = _cents(extra), _cents(lump)
    schedule = amortize(debt, start=today, extra=more, lump=lump_sum)
    strip: list[dict[str, str]] = []
    if schedule is not None:
        strip = [
            {
                "label": "Paid off",
                "value": _month(schedule.paid_off),
                "caption": f"at {money(debt.payment or 0, account.currency)} a month"
                + (f" plus {money(more, account.currency)}" if more else ""),
            },
            {
                "label": "Interest left",
                "value": money(schedule.interest, account.currency),
                "caption": "estimated from the lender's terms",
            },
            {
                "label": "Payments left",
                "value": str(schedule.months) if schedule.paid_off else "-",
            },
        ]
    return {
        "payoff_schedule": schedule,
        "payoff_strip": strip,
        "payoff_rows": [
            {
                "month": _month(step.month),
                "interest": step.interest,
                "principal": step.principal,
                "owed": step.owed,
            }
            for step in (schedule.steps if schedule else ())
        ],
        "payoff_columns": list(SCHEDULE_COLUMNS),
        "payoff_saving": extra_buys(debt, start=today, extra=more, lump=lump_sum)
        if more or lump_sum
        else None,
        "payoff_extra": extra,
        "payoff_lump": lump,
    }


@router.get(PAYOFF, include_in_schema=False)
async def page(
    request: Request,
    method: str = DEFAULT_METHOD,
    extra: str = "",
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """Every debt in payoff order, and where the next dollar goes."""
    if method not in PAYOFF_METHODS:
        method = DEFAULT_METHOD
    accounts, context = await _accounts(service, owner_user_id, None)
    debts = [d for a in accounts if (d := Debt.of(a, a.liability)) and d.owed > 0]
    plan = payoff_plan(debts, method, start=current_date(), extra=_cents(extra))
    return render(
        request,
        "pages/payoff.html",
        {
            **context,
            "method": method,
            # The method chips are the same ``range_chips`` row a time
            # window uses: a second way to pick one of a few is a second
            # thing to keep.
            "methods": list(PAYOFF_METHODS.items()),
            "method_label": PAYOFF_METHODS[method],
            "extra": extra,
            "plan": plan,
            "next_url": account_cover(plan.next.account_id) if plan.next else None,
            "plan_rows": [
                {
                    "order": str(index),
                    "debt": {
                        "label": line.debt.name,
                        "url": account_cover(line.debt.account_id),
                    },
                    "owed": line.debt.owed,
                    "rate": format_apr(line.debt.rate_bps)
                    if line.debt.rate_bps is not None
                    else "-",
                    "payment": line.debt.payment or 0,
                    "paid_off": _month(line.paid_off),
                    "interest": line.interest,
                }
                for index, line in enumerate(plan.lines, start=1)
            ],
            "plan_columns": list(PLAN_COLUMNS),
            "plan_strip": [
                {"label": "Debt-free", "value": _month(plan.debt_free)},
                {
                    "label": "Interest",
                    "value": money(plan.interest),
                    "caption": "paid in all, this order",
                },
                {
                    "label": "Saved",
                    "value": money(plan.interest_saved),
                    "caption": "against each debt on its own payment",
                },
            ],
            "unplanned": [
                {
                    "name": d.name,
                    "url": account_cover(d.account_id),
                    "owed": d.owed,
                }
                for d in plan.unplanned
            ],
        },
    )
