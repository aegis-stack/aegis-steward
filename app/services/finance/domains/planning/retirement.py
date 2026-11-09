"""The plan runs to retirement (#351-#354): what the balances on file and
a few stated assumptions imply, year by year.

The cash forecast walks two years of bills; nothing said what the
household is worth in ten, or whether it holds through retirement. Pure
arithmetic here, in cents, a year at a time: each type of asset grows
at its stated return and takes its stated contribution until the
retirement age, then the stated spending is drawn, net of the pensions
and Social Security that have started, cash first and investments next.
Debts fall away as their own schedules (``planning.debts``) say.

Every figure is a reading of what was stated, never a promise: returns
are nominal and annual, contributions and spending are flat, and taxes,
inflation and benefit increases are left to the person to fold into the
numbers they state. The simulated band says how far ordinary market
years move the answer; the chance the plan holds is the share of runs
that never go below zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import random
import statistics
from typing import Any

from app.services.finance.constants import (
    DEFAULT_END_AGE,
    DEFAULT_RETIRE_AGE,
    account_group,
    add_months,
)
from app.services.finance.domains.planning.debts import Debt, amortize, months_apart

# The three kinds of asset a plan grows, in the order they are drawn on
# in retirement. Property is stated-value: a house, a car, a pension
# reserve - last to be touched because it cannot be spent a month at a
# time.
TYPES: tuple[str, ...] = ("cash", "investments", "property")
LABELS: dict[str, str] = {
    "cash": "Cash",
    "investments": "Investments",
    "property": "Property & other",
}
# What each figure is called, on the form and on a card.
FIELD_LABELS: dict[str, str] = {
    "birth_year": "Birth year",
    "retire_age": "Retirement age",
    "end_age": "Plan to age",
    "spending": "Spending a month",
}
TYPE_FIELD_LABELS: dict[str, str] = {
    "returns": "return",
    "volatility": "swing",
    "contributions": "a month",
}


def label(field: str, kind: str | None = None) -> str:
    """ "Retirement age"; "Investments return" for a figure by type."""
    if kind is None:
        return FIELD_LABELS[field]
    return f"{LABELS[kind]} {TYPE_FIELD_LABELS[field]}"


# Stated per type, in basis points a year. The defaults are the plan
# before anyone has stated anything, shown as such.
DEFAULT_RETURNS: dict[str, int] = {"cash": 200, "investments": 600, "property": 300}
DEFAULT_VOLATILITY: dict[str, int] = {"cash": 0, "investments": 1_500, "property": 500}
# How far a plan with no birth year runs: it cannot retire, so it saves.
UNDATED_YEARS = 30
DEFAULT_RUNS = 500


def bucket(account_type: str) -> str:
    """The plan's type for an asset account: the group the account
    pages file it under, so Cash here is Banking there by construction."""
    return _BUCKETS.get(account_group(account_type), "property")


_BUCKETS = {"Banking": "cash", "Investments": "investments"}


@dataclass(frozen=True)
class Assumptions:
    """What the household states about itself and its money."""

    birth_year: int | None
    retire_age: int = DEFAULT_RETIRE_AGE
    end_age: int = DEFAULT_END_AGE
    returns: dict[str, int] | None = None  # bps a year, by type
    volatility: dict[str, int] | None = None  # bps a year, by type
    contributions: dict[str, int] | None = None  # cents a month, by type
    spending: int = 0  # cents a month, in retirement

    def rate(self, kind: str) -> int:
        return (self.returns or DEFAULT_RETURNS).get(kind, 0)

    def swing(self, kind: str) -> int:
        return (self.volatility or DEFAULT_VOLATILITY).get(kind, 0)

    def contribution(self, kind: str) -> int:
        return (self.contributions or {}).get(kind, 0)

    def age_in(self, year: int) -> int | None:
        return year - self.birth_year if self.birth_year else None

    def retired_in(self, year: int) -> bool:
        age = self.age_in(year)
        return age is not None and age >= self.retire_age

    def horizon(self, today: date) -> int:
        """How many years the plan runs from today."""
        age = self.age_in(today.year)
        return max(1, self.end_age - age) if age is not None else UNDATED_YEARS


@dataclass(frozen=True)
class Income:
    """Money that arrives on its own in retirement, from its start date."""

    name: str
    monthly: int
    starts: date
    kind: str | None = None

    def payments_in(self, after: date, through: date) -> int:
        """How many monthly payments land in ``(after, through]``."""
        # From the payment before the window to the one past it: a
        # window is a year, so fourteen steps always cover it.
        first = max(0, months_apart(self.starts, after) - 1)
        return sum(
            1
            for k in range(first, first + 14)
            if after < add_months(self.starts, k) <= through
        )


@dataclass(frozen=True)
class Year:
    """Where the plan stands on one anniversary of today."""

    on: date
    age: int | None
    retired: bool
    by_type: dict[str, int]
    debts: int

    @property
    def year(self) -> int:
        return self.on.year

    @property
    def assets(self) -> int:
        return sum(self.by_type.values())

    @property
    def net(self) -> int:
        return self.assets - self.debts


@dataclass(frozen=True)
class Path:
    """The plan as one line: today, then each anniversary to the end."""

    start: Year
    years: tuple[Year, ...]

    @property
    def at_retirement(self) -> Year | None:
        return next((y for y in self.years if y.retired), None)

    @property
    def end(self) -> Year:
        return self.years[-1] if self.years else self.start

    def saved(self) -> list[list[Any]]:
        """The path as it is kept to check against: ``[day, net]`` for
        today and each anniversary."""
        return [[y.on.isoformat(), y.net] for y in (self.start, *self.years)]


def _owed_by(
    debt: Debt, steps: tuple[Any, ...], paid_off: bool, *, through: int
) -> int:
    """What ``debt`` still owes after ``through`` payments on its schedule.
    A debt with no schedule, or one its payment never clears, is carried
    as it stands: the plan does not guess it away."""
    if not paid_off:
        return debt.owed
    if through >= len(steps):
        return 0
    return steps[through - 1].owed if through > 0 else debt.owed


# The planned debts with their schedules (and whether each pays off),
# and what the unplanned ones owe as they stand.
Schedules = tuple[list[tuple[Debt, tuple[Any, ...], bool]], int]


def scheduled(debts: list[Debt], today: date) -> Schedules:
    """Each debt's schedule from today: the same for every simulated run,
    so worked out once. A debt its terms cannot schedule is carried."""
    planned = []
    for debt in debts:
        schedule = amortize(debt, start=today)
        if schedule is not None:
            planned.append((debt, schedule.steps, schedule.paid_off is not None))
    return planned, sum(d.owed for d in debts if not d.planned)


def project(
    assumptions: Assumptions,
    balances: dict[str, int],
    debts: list[Debt],
    incomes: list[Income],
    *,
    today: date,
    returns: Any | None = None,
    schedules: Schedules | None = None,
) -> Path:
    """Net worth to the end age, a year at a time. ``returns`` may hand
    each year its own rates (``(index, kind) -> bps``), which is how the
    simulation reuses the one walk; ``schedules`` are the debts' own,
    worked out once by the caller that walks many times."""
    values = {kind: balances.get(kind, 0) for kind in TYPES}
    planned, unplanned = schedules or scheduled(debts, today)
    start = Year(
        today,
        assumptions.age_in(today.year),
        assumptions.retired_in(today.year),
        dict(values),
        sum(d.owed for d in debts),
    )
    years: list[Year] = []
    for index in range(1, assumptions.horizon(today) + 1):
        on = add_months(today, 12 * index)
        retired = assumptions.retired_in(on.year)
        for kind in TYPES:
            rate = returns(index, kind) if returns else assumptions.rate(kind)
            values[kind] += round(values[kind] * rate / 10_000)
            if not retired:
                values[kind] += assumptions.contribution(kind) * 12
        if retired:
            since = add_months(today, 12 * (index - 1))
            arrived = sum(i.monthly * i.payments_in(since, on) for i in incomes)
            short = assumptions.spending * 12 - arrived
            for kind in TYPES[:-1]:  # cash, then investments; never the house
                taken = min(max(short, 0), max(values[kind], 0))
                values[kind] -= taken
                short -= taken
            values["cash"] -= short  # what is left to draw, or the surplus
        owed = unplanned
        for debt, steps, paid_off in planned:
            through = months_apart(debt.first_month(today), on) + 1
            owed += _owed_by(debt, steps, paid_off, through=max(0, through))
        years.append(Year(on, assumptions.age_in(on.year), retired, dict(values), owed))
    return Path(start, tuple(years))


@dataclass(frozen=True)
class Band:
    """The plan under simulated returns: the tenth, fiftieth and ninetieth
    percentile of net worth each year, and the share of runs that never
    went below zero."""

    years: tuple[int, ...]
    ages: tuple[int | None, ...]
    low: tuple[int, ...]
    mid: tuple[int, ...]
    high: tuple[int, ...]
    success: float
    runs: int


def _percentile(values: list[int], share: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def simulate(
    assumptions: Assumptions,
    balances: dict[str, int],
    debts: list[Debt],
    incomes: list[Income],
    *,
    today: date,
    runs: int = DEFAULT_RUNS,
    seed: int = 0,
) -> Band:
    """``runs`` walks of the plan, each year's return on each type drawn
    around the stated rate with the stated volatility. Seeded, so the
    same plan reads the same twice."""
    draw = random.Random(seed)
    horizon = assumptions.horizon(today)
    schedules = scheduled(debts, today)
    nets: list[list[int]] = []
    held = 0
    path = project(
        assumptions, balances, debts, incomes, today=today, schedules=schedules
    )
    for _ in range(runs):
        rates = {
            (index, kind): round(
                draw.gauss(assumptions.rate(kind), assumptions.swing(kind))
            )
            for index in range(1, horizon + 1)
            for kind in TYPES
        }
        path = project(
            assumptions,
            balances,
            debts,
            incomes,
            today=today,
            returns=lambda index, kind: rates[(index, kind)],
            schedules=schedules,
        )
        line = [y.net for y in path.years]
        nets.append(line)
        held += all(net >= 0 for net in line)
    columns = [[line[i] for line in nets] for i in range(horizon)]
    return Band(
        years=tuple(y.year for y in path.years),
        ages=tuple(y.age for y in path.years),
        low=tuple(_percentile(c, 0.1) for c in columns),
        mid=tuple(int(statistics.median(c)) for c in columns),
        high=tuple(_percentile(c, 0.9) for c in columns),
        success=held / runs if runs else 0.0,
        runs=runs,
    )


def expected_on(saved: list[list[Any]], day: date) -> int:
    """Where a saved path (``Path.saved``) says net worth should be on
    ``day``: read straight between its points, held flat past either end."""
    points = [(date.fromisoformat(d), int(net)) for d, net in saved]
    if not points:
        return 0
    if day <= points[0][0]:
        return points[0][1]
    for (before, low), (after, high) in zip(points, points[1:], strict=False):
        if before <= day <= after:
            span = (after - before).days
            done = (day - before).days
            return low + round((high - low) * done / span) if span else high
    return points[-1][1]
