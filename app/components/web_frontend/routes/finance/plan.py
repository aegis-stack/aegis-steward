"""The plan runs to retirement (#351-#353): the Projected section's
second face.

The cash forecast walks two years; this walks the household's worth to
the end age, by type, from the balances on file and what is stated
under the chart. The assumptions form and the income form each post
back and swap the one block (pattern 1), so the figures shown are the
figures the saved assumptions draw.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from starlette.responses import HTMLResponse, Response

from app.components.web_frontend.filters import (
    bps_to_input,
    cents_to_input,
    dollars,
    form_bps,
    form_money,
    money,
    pct,
)
from app.components.web_frontend.nav import projected_nav, section
from app.components.web_frontend.rendering import (
    form_fields,
    form_number,
    fragment,
    render,
)
from app.services.finance.deps import get_finance_service, get_owner_user_id
from app.services.finance.service import (
    INCOME_KINDS,
    PLAN_TYPE_LABELS,
    PLAN_TYPES,
    Assumptions,
    FinancePlan,
    FinanceService,
    plan_label,
    plans,
)
from app.services.finance.utils import current_date

router = APIRouter()
PLAN = section("projected").path + "/plan"
INCOME = PLAN + "/income"
BODY = "partials/plan/body.html"
# Simulated runs behind the page's band.
RUNS = 300

TYPE_COLUMNS = (
    {"key": "type", "label": "Type"},
    {"key": "today", "label": "Today", "kind": "money", "align": "right"},
    {"key": "retired", "label": "At retirement", "kind": "money", "align": "right"},
    {"key": "end", "label": "At the end", "kind": "money", "align": "right"},
)


def _form_values(
    stated: Assumptions, inputs: plans.Inputs, row: FinancePlan | None
) -> dict[str, str]:
    """What the assumptions form shows: the stated figures, else the
    defaults, with the ledger's measured figures as placeholders."""
    contributions = dict(row.contributions) if row else {}
    values = {
        "birth_year": str(stated.birth_year or ""),
        "retire_age": str(stated.retire_age),
        "end_age": str(stated.end_age),
        "spending": cents_to_input(row.spending)
        if row and row.spending is not None
        else "",
        "spending_measured": cents_to_input(inputs.measured_spending),
    }
    for kind in PLAN_TYPES:
        values[f"return_{kind}"] = bps_to_input(stated.rate(kind))
        values[f"swing_{kind}"] = bps_to_input(stated.swing(kind))
        values[f"put_{kind}"] = (
            cents_to_input(contributions[kind]) if kind in contributions else ""
        )
        values[f"put_{kind}_measured"] = cents_to_input(
            inputs.measured_contributions.get(kind, 0)
        )
    return values


async def plan_context(
    service: FinanceService,
    owner_user_id: int | None,
    *,
    outcome: plans.Outcome | None = None,
    errors: list[str] | None = None,
    income_errors: list[str] | None = None,
) -> dict[str, Any]:
    """The page's context from the plan as it stands, or from ``outcome``
    when the request just saved it."""
    today = current_date()
    outcome = outcome or await plans.run_plan(
        service.db, owner_user_id=owner_user_id, today=today, runs=RUNS
    )
    path, band, stated = outcome.path, outcome.band, outcome.assumptions
    retired = path.at_retirement
    strip = [{"label": "Net worth today", "value": money(path.start.net)}]
    if retired is not None:
        strip.append(
            {
                "label": "At retirement",
                "value": money(retired.net),
                "caption": f"{retired.year}, age {retired.age}",
            }
        )
    strip.append(
        {
            "label": f"At {path.end.year}",
            "value": money(path.end.net),
            "caption": f"age {path.end.age}"
            if path.end.age
            else f"{len(path.years)} years out",
            "tone": "error" if path.end.net < 0 else None,
        }
    )
    strip.append(
        {
            "label": "Chance it holds",
            "value": pct(band.success),
            "caption": f"never below zero, {band.runs} runs",
            "tone": "ok"
            if band.success >= 0.8
            else "warn"
            if band.success >= 0.5
            else "error",
        }
    )
    return {
        "section": section("projected"),
        **projected_nav("plan"),
        "plan_page": PLAN,
        "income_page": INCOME,
        "outcome": outcome,
        "strip": strip,
        "chart": {
            "labels": [str(year) for year in band.years],
            "series": [
                {
                    "label": "Low",
                    "values": [dollars(v) for v in band.low],
                    "band": "low",
                },
                {
                    "label": "High",
                    "values": [dollars(v) for v in band.high],
                    "band": "high",
                },
                {"label": "Likely", "values": [dollars(v) for v in band.mid]},
            ],
        },
        "type_columns": list(TYPE_COLUMNS),
        "type_rows": [
            {
                "type": PLAN_TYPE_LABELS[kind],
                "today": path.start.by_type[kind],
                "retired": retired.by_type[kind] if retired else None,
                "end": path.end.by_type[kind],
            }
            for kind in PLAN_TYPES
        ]
        + [
            {
                "type": "Debts",
                "today": -path.start.debts,
                "retired": -retired.debts if retired else None,
                "end": -path.end.debts,
            }
        ],
        "values": _form_values(stated, outcome.inputs, outcome.row),
        "types": [(kind, PLAN_TYPE_LABELS[kind]) for kind in PLAN_TYPES],
        "errors": errors or [],
        "income_errors": income_errors or [],
        "incomes": [
            {
                "name": income.name,
                "monthly": income.monthly,
                "starts": f"{income.starts:%b %Y}",
                "kind": INCOME_KINDS.get(income.kind or "", ""),
            }
            for income in outcome.inputs.incomes
        ],
        "income_kinds": INCOME_KINDS,
        "today": today,
    }


@router.get(PLAN, include_in_schema=False)
async def page(
    request: Request,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    return render(
        request, "pages/plan.html", await plan_context(service, owner_user_id)
    )


def _body(context: dict[str, Any], status_code: int = 200) -> Response:
    return HTMLResponse(fragment(BODY, **context), status_code=status_code)


@router.post(PLAN, include_in_schema=False)
async def save(
    request: Request,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """The assumptions, stated: kept with the path they draw."""
    form = await form_fields(request)
    try:
        stated = {
            "birth_year": form_number(form.get("birth_year"), plan_label("birth_year")),
            "retire_age": form_number(form.get("retire_age"), plan_label("retire_age"))
            or Assumptions.retire_age,
            "end_age": form_number(form.get("end_age"), plan_label("end_age"))
            or Assumptions.end_age,
            "returns": {
                kind: bps
                for kind in PLAN_TYPES
                if (
                    bps := form_bps(
                        form.get(f"return_{kind}"), plan_label("returns", kind)
                    )
                )
                is not None
            },
            "volatility": {
                kind: bps
                for kind in PLAN_TYPES
                if (
                    bps := form_bps(
                        form.get(f"swing_{kind}"), plan_label("volatility", kind)
                    )
                )
                is not None
            },
            "contributions": {
                kind: cents
                for kind in PLAN_TYPES
                if (
                    cents := form_money(
                        form.get(f"put_{kind}"), plan_label("contributions", kind)
                    )
                )
                is not None
            },
            "spending": form_money(form.get("spending"), plan_label("spending")),
        }
    except ValueError as error:
        return _body(
            await plan_context(service, owner_user_id, errors=[str(error)]), 422
        )
    outcome = await plans.save_plan(
        service.db,
        owner_user_id=owner_user_id,
        today=current_date(),
        runs=RUNS,
        **stated,
    )
    await service.db.commit()
    return _body(await plan_context(service, owner_user_id, outcome=outcome))


@router.post(INCOME, include_in_schema=False)
async def income(
    request: Request,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """A pension or Social Security estimate, typed: income from its
    start (#352)."""
    form = await form_fields(request)
    errors: list[str] = []
    name = (form.get("name") or "").strip()
    kind = form.get("kind") or ""
    monthly: int | None = None
    try:
        monthly = form_money(form.get("monthly"), "Monthly amount")
    except ValueError as exc:
        errors.append(str(exc))
    if not name:
        errors.append("Name the income.")
    if kind not in INCOME_KINDS:
        errors.append("Say whether it is a pension or Social Security.")
    if monthly is None and not errors:
        errors.append("Monthly amount must be an amount.")
    try:
        starts = date.fromisoformat(form.get("starts") or "")
    except ValueError:
        starts = None
        errors.append("Say when it starts.")
    if errors or starts is None or monthly is None:
        return _body(
            await plan_context(service, owner_user_id, income_errors=errors), 422
        )
    await plans.declare_income(
        service.db,
        owner_user_id=owner_user_id,
        name=name,
        kind=kind,
        monthly=monthly,
        starts=starts,
    )
    await service.db.commit()
    return _body(await plan_context(service, owner_user_id))
