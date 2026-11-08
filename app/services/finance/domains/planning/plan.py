"""The plan runs to retirement, on the ledger (#351-#354).

``retirement`` is the arithmetic; this is where it meets the rows: the
accounts in net worth sorted into the plan's types, the debts' terms,
the pensions declared as income, the assumptions kept per household,
and the path saved with them for the quarterly check to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.finance.constants import INCOME_KIND, INCOME_KINDS
from app.services.finance.domains.detection.insights.commitments import (
    is_active_commitment,
    monthly_share,
)
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.ledger.accounts import effective_balance
from app.services.finance.domains.ledger.cash_flow import (
    CashflowMonth,
    monthly_cashflow,
)
from app.services.finance.domains.ledger.net_worth_rule import counts_in_net_worth
from app.services.finance.domains.planning.debts import Debt
from app.services.finance.domains.planning.goals.reads import goal_debts
from app.services.finance.domains.planning.queries import plan_row
from app.services.finance.domains.planning.recurring import queries as stream_queries
from app.services.finance.domains.planning.recurring.streams import (
    create_recurring_stream,
)
from app.services.finance.domains.planning.retirement import (
    DEFAULT_RETURNS,
    DEFAULT_RUNS,
    DEFAULT_VOLATILITY,
    TYPES,
    Assumptions,
    Band,
    Income,
    Path,
    bucket,
    expected_on,
    project,
    simulate,
)
from app.services.finance.models import FinancePlan, FinanceRecurringStream
from app.services.shared.queries import stored_owner

# Months of ledger the measured spending figure averages over.
SPENDING_MONTHS = 12


@dataclass(frozen=True)
class Inputs:
    """What the ledger says the plan starts from."""

    balances: dict[str, int]  # by type, cents
    debts: list[Debt]
    incomes: list[Income]
    measured_contributions: dict[str, int]  # cents a month, by type
    measured_spending: int  # cents a month, the last year's average


@dataclass(frozen=True)
class Outcome:
    """The plan, run: what was assumed, what it started from, the line
    and the band around it."""

    assumptions: Assumptions
    inputs: Inputs
    path: Path
    band: Band
    row: FinancePlan | None


def stated_assumptions(
    row: FinancePlan | None, inputs: Inputs | None = None
) -> Assumptions:
    """The row as assumptions; given the ledger's ``inputs``, a figure
    never stated is the measured one; without them, only what was said."""
    measured = inputs.measured_contributions if inputs else {}
    stated = dict(row.contributions) if row else {}
    spending = (row.spending if row else None) or (
        inputs.measured_spending if inputs else 0
    )
    return Assumptions(
        birth_year=row.birth_year if row else None,
        retire_age=row.retire_age if row else Assumptions.retire_age,
        end_age=row.end_age if row else Assumptions.end_age,
        returns=dict(row.returns) if row and row.returns else None,
        volatility=dict(row.volatility) if row and row.volatility else None,
        contributions={**measured, **stated},
        spending=spending,
    )


async def plan_inputs(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    months: list[CashflowMonth] | None = None,
) -> Inputs:
    """The balances in net worth by type, the debts with their terms, the
    retirement income declared, and what the ledger measures going into
    each type and out each month. ``months`` are the cashflow months a
    caller already holds (the analyst's report), else the last year's."""
    accounts = await ledger_queries.live_accounts_for_owner(
        db, owner_user_id=owner_user_id
    )
    counted = [
        a for a in accounts if a.id is not None and counts_in_net_worth(a, today)
    ]
    ids = [a.id for a in counted if a.id is not None]
    activity = await ledger_queries.transaction_totals_by_account(
        db, owner_user_id=owner_user_id, account_ids=ids
    )
    # The same reading of a debt the goals and the payoff page make.
    debts = [d for d in (await goal_debts(db, counted)).values() if d.owed > 0]
    balances = dict.fromkeys(TYPES, 0)
    for account in counted:
        if account.classification == "liability":
            continue
        balances[bucket(account.account_type)] += effective_balance(
            current_balance=account.current_balance,
            balance_as_of=account.balance_as_of,
            classification=account.classification,
            activity_balance=activity.get(account.id or 0, 0),
        )
    streams = await stream_queries.active_streams(db, owner_user_id=owner_user_id)
    # What lands in the investments each month, measured: the inflow
    # streams on those accounts.
    invested = {
        a.id
        for a in counted
        if a.classification == "asset" and bucket(a.account_type) == "investments"
    }
    contributions: dict[str, int] = {}
    for stream in streams:
        if (
            stream.direction == "inflow"
            and stream.account_id in invested
            and is_active_commitment(stream, today)
        ):
            contributions["investments"] = contributions.get(
                "investments", 0
            ) + monthly_share(stream)
    if months is None:
        months = await monthly_cashflow(
            db, owner_user_id=owner_user_id, months=SPENDING_MONTHS, today=today
        )
    spent = [m.expense for m in months if m.expense]
    return Inputs(
        balances=balances,
        debts=debts,
        incomes=_incomes(streams),
        measured_contributions=contributions,
        measured_spending=round(sum(spent) / len(spent)) if spent else 0,
    )


def _incomes(streams: list[FinanceRecurringStream]) -> list[Income]:
    return [
        Income(
            s.name,
            monthly_share(s),
            s.next_expected_date,
            (s.metadata_ or {}).get(INCOME_KIND),
        )
        for s in streams
        if s.direction == "inflow"
        and s.next_expected_date is not None
        and (s.metadata_ or {}).get(INCOME_KIND) in INCOME_KINDS
    ]


async def declare_income(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    name: str,
    kind: str,
    monthly: int,
    starts: date,
    account_id: int | None = None,
) -> FinanceRecurringStream:
    """A pension or Social Security estimate as the income stream it
    will be (#352): monthly, from its start date, marked with its kind
    so the plan counts it from then and the forecast carries it once
    the date is in reach."""
    return await create_recurring_stream(
        db,
        owner_user_id=owner_user_id,
        name=name,
        direction="inflow",
        frequency="monthly",
        expected_amount=monthly,
        next_expected_date=starts,
        account_id=account_id,
        income_kind=kind,
    )


async def save_plan(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    birth_year: int | None = None,
    retire_age: int = Assumptions.retire_age,
    end_age: int = Assumptions.end_age,
    returns: dict[str, int] | None = None,
    volatility: dict[str, int] | None = None,
    contributions: dict[str, int] | None = None,
    spending: int | None = None,
    runs: int = DEFAULT_RUNS,
    row: FinancePlan | None = None,
) -> Outcome:
    """Keep what was stated, and the path it draws from today: the line
    the quarterly check reads the plan's expectation off. The plan as
    saved comes back run, so the page that saved it draws it without
    reading it again. A caller that already read the ``row`` hands it in."""
    row = (
        row
        or await plan_row(db, owner_user_id)
        or FinancePlan(owner_user_id=stored_owner(owner_user_id))
    )
    row.birth_year = birth_year
    row.retire_age = retire_age
    row.end_age = end_age
    row.returns = dict(returns or {})
    row.volatility = dict(volatility or {})
    row.contributions = dict(contributions or {})
    row.spending = spending
    inputs = await plan_inputs(db, owner_user_id=owner_user_id, today=today)
    outcome = _run(row, inputs, today=today, runs=runs)
    row.path = outcome.path.saved()
    row.path_saved_on = today
    row.updated_at = utcnow()
    db.add(row)
    await db.flush()
    return outcome


# The figures a plan states, as ``save_plan`` takes them.
FIELDS = (
    "birth_year",
    "retire_age",
    "end_age",
    "returns",
    "volatility",
    "contributions",
    "spending",
)
# What a per-type figure lays over when one type is amended: a rate or
# swing falls back to the defaults only as a whole dict, so the others
# are filled in; a contribution never stated stays measured.
_BASES: dict[str, dict[str, int]] = {
    "returns": DEFAULT_RETURNS,
    "volatility": DEFAULT_VOLATILITY,
    "contributions": {},
}


async def amend_plan(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    changes: dict[str, Any],
    runs: int = DEFAULT_RUNS,
) -> Outcome:
    """Only what is given changes (#353): the card's half of the form's
    full save, laid over the row's own figures, never over the measured
    or default ones standing in for them."""
    row = await plan_row(db, owner_user_id) or FinancePlan(
        owner_user_id=stored_owner(owner_user_id)
    )
    fields = {name: getattr(row, name) for name in FIELDS}
    for name, value in changes.items():
        fields[name] = (
            (fields[name] or _BASES[name]) | value if name in _BASES else value
        )
    return await save_plan(
        db, owner_user_id=owner_user_id, today=today, runs=runs, row=row, **fields
    )


def _run(row: FinancePlan | None, inputs: Inputs, *, today: date, runs: int) -> Outcome:
    assumptions = stated_assumptions(row, inputs)
    args = (assumptions, inputs.balances, inputs.debts, inputs.incomes)
    return Outcome(
        assumptions=assumptions,
        inputs=inputs,
        path=project(*args, today=today),
        band=simulate(*args, today=today, runs=runs),
        row=row,
    )


async def run_plan(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    runs: int = DEFAULT_RUNS,
    months: list[CashflowMonth] | None = None,
) -> Outcome:
    """The plan as it stands: the line, and the band around it."""
    row = await plan_row(db, owner_user_id)
    inputs = await plan_inputs(
        db, owner_user_id=owner_user_id, today=today, months=months
    )
    return _run(row, inputs, today=today, runs=runs)


# How far off the path still counts as on it.
TOLERANCE = 0.02


@dataclass(frozen=True)
class Check:
    """Actual against the saved path, on a day."""

    expected: int
    actual: int
    saving: int  # cents a month, measured
    planned_saving: int  # cents a month, as the plan assumed

    @property
    def gap(self) -> int:
        return self.actual - self.expected

    @property
    def on_track(self) -> bool:
        return abs(self.gap) <= abs(self.expected) * TOLERANCE


async def check_plan(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    row: FinancePlan | None = None,
) -> Check | None:
    """Where the household stands against the path its plan saved; None
    before a plan was saved. The job that walks every plan hands its
    ``row`` in; a caller with one household lets it be read."""
    row = row or await plan_row(db, owner_user_id)
    if row is None or not row.path:
        return None
    inputs = await plan_inputs(db, owner_user_id=owner_user_id, today=today)
    assumptions = stated_assumptions(row, inputs)
    return Check(
        expected=expected_on(row.path, today),
        actual=sum(inputs.balances.values()) - sum(d.owed for d in inputs.debts),
        saving=sum(inputs.measured_contributions.values()),
        planned_saving=sum(assumptions.contribution(kind) for kind in TYPES),
    )
