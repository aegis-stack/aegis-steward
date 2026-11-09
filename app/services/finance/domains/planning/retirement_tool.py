"""The plan to retirement, read by an agent (#353).

Beside the plan it reads rather than in ``tools``, which is at its
budget: the one read that runs a simulation.
"""

from __future__ import annotations

from app.core.db import get_async_session
from app.core.tools import register_tool
from app.services.finance.domains.planning.retirement import DEFAULT_RUNS
from app.services.finance.schemas.agent_tools import PlanPoint, RetirementPlan


async def retirement(runs: int = DEFAULT_RUNS) -> RetirementPlan:
    """The plan to retirement, computed: net worth walked to the end age
    by type from the balances on file and the stated assumptions
    ('assumptions'), 'today' by type, 'at_retirement' and 'at_end' (year,
    age, 'net_worth_cents'), the 'band' of simulated returns ('years',
    'ages', 'low_cents', 'likely_cents', 'high_cents': the tenth,
    fiftieth and ninetieth percentile each year) and 'chance_of_holding',
    the share of 'runs' that never went below zero. 'incomes' are the
    pensions and Social Security declared, each from its start.

    Read these figures rather than estimating them: the band and the
    chance are computed in code from the same plan the Projected page
    shows, and 'plan_saved' says whether the household has stated its
    own assumptions or the defaults are in charge.
    """
    from app.services.finance.domains.planning.plan import run_plan
    from app.services.finance.domains.planning.retirement import TYPES, Year
    from app.services.finance.utils import current_date

    today = current_date()
    async with get_async_session() as session:
        outcome = await run_plan(session, owner_user_id=None, today=today, runs=runs)
    stated, path, band = outcome.assumptions, outcome.path, outcome.band

    def point(year: Year) -> PlanPoint:
        return {"year": year.year, "age": year.age, "net_worth_cents": year.net}

    return {
        "as_of": today.isoformat(),
        "plan_saved": outcome.row is not None,
        "assumptions": {
            "birth_year": stated.birth_year,
            "retire_age": stated.retire_age,
            "end_age": stated.end_age,
            "returns_bps": {kind: stated.rate(kind) for kind in TYPES},
            "volatility_bps": {kind: stated.swing(kind) for kind in TYPES},
            "contributions_cents": {kind: stated.contribution(kind) for kind in TYPES},
            "spending_cents": stated.spending,
        },
        "today": {
            "by_type_cents": dict(path.start.by_type),
            "debts_cents": path.start.debts,
            "net_worth_cents": path.start.net,
        },
        "at_retirement": point(path.at_retirement) if path.at_retirement else None,
        "at_end": point(path.end),
        "band": {
            "years": list(band.years),
            "ages": list(band.ages),
            "low_cents": list(band.low),
            "likely_cents": list(band.mid),
            "high_cents": list(band.high),
        },
        "chance_of_holding": band.success,
        "runs": band.runs,
        "incomes": [
            {
                "name": income.name,
                "kind": income.kind,
                "monthly_cents": income.monthly,
                "starts": income.starts.isoformat(),
            }
            for income in outcome.inputs.incomes
        ],
    }


register_tool(
    "retirement",
    retirement,
    description=(
        "The plan to retirement: net worth by type to the end age, "
        "the band and the chance it holds"
    ),
    effect="read",
    replace=True,
)
