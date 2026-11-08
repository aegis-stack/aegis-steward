"""Debts that pay down (#347-#350): what the terms on file imply.

A loan's detail row has held its balance, rate and payment since the
beginning, and nothing computed what they mean: when it ends, what the
interest comes to, what $50 more a month would buy. Pure arithmetic
here, in cents, with one month's interest the way the loan split already
reckons it (``monthly_interest``), so the schedule and the split cannot
disagree about a month.

Every answer is a reading of the lender's stated terms, not the ledger's
history: a payment that never changes, interest on what is owed at the
start of each month, extra money to principal only where the lender
says it goes there. Unconfirmed terms are carried as unconfirmed, never
guessed to the payer's advantage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.finance.constants import add_months
from app.services.finance.domains.detection.insights.formatting import card_apr_bps
from app.services.finance.domains.detection.transfers.loans import monthly_interest

# A schedule longer than this is "never": a payment that only just
# covers the interest would otherwise run for centuries.
LONGEST_MONTHS = 600
METHODS: dict[str, str] = {
    "avalanche": "highest rate first",
    "snowball": "smallest balance first",
}


@dataclass(frozen=True)
class Debt:
    """One debt as its lender states it: what is owed, what it costs, what
    is paid each month (``escrow`` of that going to taxes and insurance,
    not the loan), and what extra money does."""

    account_id: int
    name: str
    owed: int  # cents, positive
    rate_bps: int | None
    payment: int | None  # cents a month, as billed
    escrow: int = 0
    extra_treatment: str | None = None  # terms.EXTRA_PAYMENT keys
    prepayment_penalty: str | None = None  # terms.PREPAYMENT keys
    next_due: date | None = None

    @property
    def toward(self) -> int | None:
        """What each payment puts toward the loan itself."""
        if self.payment is None:
            return None
        return max(0, self.payment - self.escrow)

    @property
    def planned(self) -> bool:
        """Whether a schedule can be drawn at all."""
        return self.rate_bps is not None and self.toward is not None

    @property
    def extra_applies(self) -> bool:
        """Whether extra money shortens the loan: it does unless the
        lender applies it to future instalments."""
        return self.extra_treatment != "future_installments"

    def first_month(self, today: date) -> date:
        """The month the next payment falls in: the lender's due date
        where one is on file, else this month. Every surface starts its
        schedule here, so none can disagree with another by a month."""
        return max(today, self.next_due) if self.next_due else today

    @classmethod
    def of(cls, account: Any, terms: Any | None) -> Debt | None:
        """The account as a debt, from its liability terms (the detail
        row or its summary, which name these fields alike): the lender's
        figure for what is owed where it has one, else the ledger's
        balance. None for an asset; no terms at all is still a debt -
        what is owed, and nothing more."""
        if account.classification != "liability" or account.id is None:
            return None
        balance = abs(account.current_balance or 0)
        if terms is None:
            return cls(account.id, account.name, balance, None, None)
        owed = terms.outstanding_balance
        return cls(
            account_id=account.id,
            name=account.name,
            owed=max(0, balance if owed is None else owed),
            rate_bps=card_apr_bps(terms),
            payment=terms.minimum_payment_amount,
            escrow=terms.escrow_amount or 0,
            extra_treatment=terms.extra_payment_treatment,
            prepayment_penalty=terms.prepayment_penalty,
            next_due=terms.next_payment_due_date,
        )


@dataclass(frozen=True)
class Step:
    """One month of a schedule, after its payment."""

    month: date
    interest: int
    principal: int
    owed: int


@dataclass(frozen=True)
class Schedule:
    """The loan paid as its terms say. ``paid_off`` is None, and ``steps``
    empty, when the payment never gets there."""

    steps: tuple[Step, ...]
    paid_off: date | None
    interest: int

    @property
    def months(self) -> int:
        return len(self.steps)


NEVER = Schedule(steps=(), paid_off=None, interest=0)


def _schedule(debt: Debt, start: date, extra: int, lump: int) -> Schedule:
    """``amortize`` for a debt known to be planned."""
    rate, toward = debt.rate_bps or 0, debt.toward or 0
    if not debt.extra_applies:
        extra, lump = 0, 0
    first = debt.first_month(start)
    owed = debt.owed
    steps: list[Step] = []
    interest_total = 0
    for index in range(LONGEST_MONTHS):
        if owed <= 0:
            break
        interest = monthly_interest(owed, rate)
        available = toward + extra + (lump if index == 0 else 0) - interest
        if available <= 0:
            return NEVER
        principal = min(owed, available)
        owed -= principal
        interest_total += interest
        steps.append(Step(add_months(first, index), interest, principal, owed))
    if owed > 0:
        return NEVER
    return Schedule(
        steps=tuple(steps),
        paid_off=steps[-1].month if steps else first,
        interest=interest_total,
    )


def amortize(
    debt: Debt, *, start: date, extra: int = 0, lump: int = 0
) -> Schedule | None:
    """The schedule from today (``start``), the first payment in the
    debt's due month: each month's interest on what is owed, the rest of
    the payment to principal, plus ``extra`` a month and ``lump`` with
    the first payment where the lender lets extra reduce principal. None
    when the terms cannot say."""
    return _schedule(debt, start, extra, lump) if debt.planned else None


@dataclass(frozen=True)
class Saving:
    """What paying more buys, against the schedule as it stands."""

    months_sooner: int
    interest_saved: int
    applies: bool  # the lender puts extra toward principal
    unconfirmed: bool  # nobody has asked the lender how extra is applied
    penalty: bool  # an early payoff carries a penalty


def extra_buys(
    debt: Debt, *, start: date, extra: int = 0, lump: int = 0
) -> Saving | None:
    """``extra`` a month and/or ``lump`` now: months and interest saved,
    honoring how the lender treats money above the payment. None when
    the loan has no schedule to save against."""
    base = amortize(debt, start=start)
    if base is None or base.paid_off is None:
        return None
    more = _schedule(debt, start, extra, lump)
    return Saving(
        months_sooner=base.months - more.months,
        interest_saved=base.interest - more.interest,
        applies=debt.extra_applies,
        unconfirmed=debt.extra_treatment in (None, "unknown"),
        penalty=debt.prepayment_penalty == "penalty",
    )


def extra_to_finish_by(debt: Debt, *, start: date, by: date) -> int | None:
    """The least extra a month that has the loan paid off by ``by``: zero
    when the schedule already gets there, None when no extra can (the
    terms cannot say, or the lender only pays ahead with it)."""
    if not debt.planned or not debt.extra_applies:
        return None
    base = _schedule(debt, start, 0, 0)
    if base.paid_off is not None and base.paid_off <= by:
        return 0
    low, high = 0, debt.owed
    while low < high:
        mid = (low + high) // 2
        tried = _schedule(debt, start, mid, 0).paid_off
        if tried is not None and tried <= by:
            high = mid
        else:
            low = mid + 1
    return low


def ordered(debts: list[Debt], method: str) -> list[Debt]:
    """The debts as a payoff method lines them up: avalanche by rate, the
    dearest first (a rate nobody knows sorts last); snowball by balance,
    the smallest first."""
    if method == "snowball":
        return sorted(debts, key=lambda d: (d.owed, d.name))
    return sorted(
        debts,
        key=lambda d: (d.rate_bps is None, -(d.rate_bps or 0), -d.owed, d.name),
    )


@dataclass(frozen=True)
class Line:
    """One debt under the plan."""

    debt: Debt
    paid_off: date | None
    interest: int


@dataclass(frozen=True)
class Plan:
    """Every debt paid in order: each payment kept up, the extra and every
    freed payment poured onto the first debt still open."""

    lines: tuple[Line, ...]
    unplanned: tuple[Debt, ...]  # terms too thin to schedule
    debt_free: date | None
    interest: int
    alone_interest: int  # each debt on its own payment, no rolling

    @property
    def next(self) -> Debt | None:
        """Where the next dollar goes."""
        return self.lines[0].debt if self.lines else None

    @property
    def interest_saved(self) -> int:
        return self.alone_interest - self.interest


def _months_apart(start: date, later: date) -> int:
    return (later.year - start.year) * 12 + later.month - start.month


def plan(debts: list[Debt], method: str, *, start: date, extra: int = 0) -> Plan:
    """The debts paid down by ``method`` with ``extra`` a month on top.
    Month by month from today (``start``): each debt due that month pays
    its interest and its own payment; the extra, and the payments of
    debts already paid off, go to the first open debt in order (to
    principal, where its lender allows). A debt whose terms cannot be
    scheduled is listed apart."""
    ranked = ordered(debts, method)
    lined = [d for d in ranked if d.planned]
    unplanned = tuple(d for d in ranked if not d.planned)
    owed = {d.account_id: d.owed for d in lined}
    first = {d.account_id: _months_apart(start, d.first_month(start)) for d in lined}
    paid_off: dict[int, date] = {}
    interest: dict[int, int] = {d.account_id: 0 for d in lined}
    freed = 0  # payments of debts paid off, rolled on
    for index in range(LONGEST_MONTHS):
        if all(owed[d.account_id] <= 0 for d in lined):
            break
        month = add_months(start, index)
        due = [
            d for d in lined if owed[d.account_id] > 0 and index >= first[d.account_id]
        ]
        pool = extra + freed
        for debt in due:
            charge = monthly_interest(owed[debt.account_id], debt.rate_bps or 0)
            interest[debt.account_id] += charge
            # A payment short of its interest grows the debt: the plan
            # says so rather than hiding it.
            owed[debt.account_id] -= min(
                owed[debt.account_id], (debt.toward or 0) - charge
            )
        for debt in due:
            if pool <= 0:
                break
            if not debt.extra_applies or owed[debt.account_id] <= 0:
                continue
            put = min(pool, owed[debt.account_id])
            owed[debt.account_id] -= put
            pool -= put
        for debt in due:
            if owed[debt.account_id] <= 0:
                paid_off[debt.account_id] = month
                freed += debt.toward or 0
    lines = tuple(
        Line(d, paid_off.get(d.account_id), interest[d.account_id]) for d in lined
    )
    alone = [_schedule(d, start, 0, 0) for d in lined]
    return Plan(
        lines=lines,
        unplanned=unplanned,
        debt_free=max((line.paid_off for line in lines if line.paid_off), default=None)
        if len(paid_off) == len(lined)
        else None,
        interest=sum(interest.values()),
        alone_interest=sum(s.interest for s in alone),
    )
