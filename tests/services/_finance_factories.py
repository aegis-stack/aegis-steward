"""Shared factories for the finance test suite.

One canonical seed per row kind. Before this file, ``_account`` was
re-typed in 17 test files and ``_category``'s slug rule had already
drifted between copies ("&" handled in one, not the others) - which is
the failure mode a shared factory exists to prevent. Files alias these
on import (``from tests.services._finance_factories import seed_account
as _account``) so call sites stay short.

Keep factories SUPERSETS: add keywords with the old defaults, never
change a default - fifteen files inherit it.

The readers at the bottom are the same idea for reading back: one way
to pick a limit's projection points, one way to count queries.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import event
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinanceCategory
from app.services.finance.service import FinanceService


async def seed_account(
    svc: FinanceService,
    name: str = "Checking",
    account_type: str = "checking",
    classification: str = "asset",
    owner_user_id: int = 1,
    **kwargs: Any,
):
    """A manual account; defaults to the plain checking account most tests want."""
    return await svc.create_manual_account(
        name=name,
        account_type=account_type,
        classification=classification,
        owner_user_id=owner_user_id,
        **kwargs,
    )


async def seed_household(svc: Any, db: AsyncSession) -> None:
    """Cash, a brokerage account and a house: the plan to retirement's
    three types, committed."""
    await seed_account(svc, "Checking", current_balance=1_000_000)
    await seed_account(
        svc, "Brokerage", account_type="brokerage", current_balance=10_000_000
    )
    await seed_account(
        svc, "House", account_type="property", current_balance=40_000_000
    )
    await db.commit()


async def seed_loan(
    svc: FinanceService,
    db: Any,
    name: str = "Pool loan",
    *,
    account_type: str = "loan",
    current_balance: int | None = None,
    owner_user_id: int = 1,
    **terms: Any,
) -> int:
    """A liability with its lender's terms on file: by default the
    hand-checked loan of the debt tests ($1,000 at 12%, $100 a month,
    extra to principal, no penalty). ``terms`` are ``LoanTermsPayload``
    fields; pass one as None to leave it unstated."""
    from app.services.finance.domains.writes.terms import (
        LoanTermsPayload,
        loan_terms_execute,
    )

    account = await seed_account(
        svc,
        name=name,
        account_type=account_type,
        classification="liability",
        owner_user_id=owner_user_id,
        **({"current_balance": current_balance} if current_balance is not None else {}),
    )
    stated: dict[str, Any] = {
        "outstanding_balance": 100_000,
        "interest_rate_bps": 1_200,
        "minimum_payment_amount": 10_000,
        "extra_payment_treatment": "principal",
        "prepayment_penalty": "none",
    } | terms
    await loan_terms_execute(
        db, LoanTermsPayload(account_id=int(account.id), **stated), owner_user_id
    )
    await db.commit()
    return int(account.id)


async def seed_category(db: Any, name: str) -> FinanceCategory:
    """An expense category with the FULL slug normalization - one copy had
    "&" handling and two did not, which is exactly the drift this fixes."""
    row = FinanceCategory(
        owner_user_id=1,
        name=name,
        slug=name.lower().replace(" ", "-").replace(":", "-").replace("&", "and"),
        classification="expense",
    )
    db.add(row)
    await db.flush()
    return row


async def seed_spend_series(
    svc: FinanceService,
    account_id: int,
    days: list[date],
    cents: int = -2_500,
    name: str = "ACME",
) -> list[Any]:
    """One transaction per day - the rhythm the detection tests feed."""
    return [
        await svc.create_transaction(
            account_id=account_id,
            amount=cents,
            txn_date=day,
            owner_user_id=1,
            name=name,
        )
        for day in days
    ]


async def live_streams(db: Any) -> list[Any]:
    """Live (non-deleted) recurring streams, unordered."""
    from sqlmodel import select

    from app.services.finance.models import FinanceRecurringStream

    return list(
        (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).all()
    )


async def seed_txn(
    svc: FinanceService,
    account_id: int,
    amount: int,
    day: date,
    *,
    name: str | None = None,
    category_id: int | None = None,
    owner_user_id: int = 1,
):
    """One transaction. The canonical signature; files with their own
    argument conventions keep a two-line wrapper that delegates here."""
    return await svc.create_transaction(
        account_id=account_id,
        amount=amount,
        txn_date=day,
        owner_user_id=owner_user_id,
        name=name,
        category_id=category_id,
    )


async def seed_charge(db: AsyncSession, cents: int, day: date, name: str) -> int:
    """One posted charge on an account of its own, by id: what waiting
    paper (a receipt, a check scan, an order) is matched against."""
    svc = FinanceService(db)
    account = await seed_account(svc, name=f"VISA {name} {day}")
    row = await seed_txn(svc, int(account.id or 0), cents, day, name=name)
    return int(row.id or 0)


async def pending_cards(
    db: AsyncSession, change_type: str, status: str | None = "pending"
) -> list[Any]:
    """The queue's cards of one type, oldest first."""
    from app.services.finance.domains.writes.queue import list_changes

    return list(await list_changes(db, status=status, change_type=change_type))


async def category_id(svc: FinanceService, hint: str) -> int:
    """The id of the category a ``"Parent:Child"`` hint names, made if new."""
    category = await svc.get_or_create_category_from_hint(hint)
    assert category.id is not None
    return category.id


async def seed_monthly_spend(
    svc: FinanceService, category_id: int, spends: dict[int, int]
) -> None:
    """``{period: cents}`` spent on one category, one charge on the 10th
    of each month, from one account."""
    account = await seed_account(svc)
    for period, cents in spends.items():
        await seed_txn(
            svc,
            account.id,
            -cents,
            date(period // 100, period % 100, 10),
            category_id=category_id,
        )


async def seed_limit(
    svc: FinanceService,
    category_id: int | None,
    cents: int,
    *,
    owner_user_id: int | None = 1,
    period_month: int | None = None,
    rollover: bool | None = None,
):
    """One limit on a category (or on nothing: the overall limit). The
    canonical call; files with their own argument conventions keep a
    two-line wrapper that delegates here."""
    return await svc.upsert_budget_line(
        owner_user_id=owner_user_id,
        period_month=period_month,
        category_id=category_id,
        payee_key=None,
        payee_label=None,
        allocated_amount=cents,
        rollover_enabled=rollover,
    )


async def seed_payee_txn(
    svc: FinanceService,
    account_id: int,
    name: str,
    day: date,
    cents: int,
):
    """The payee-first convention two suites share: name up front, because
    the payee IS the subject under test."""
    return await seed_txn(svc, account_id, cents, day, name=name)


async def seed_stream(
    svc: FinanceService,
    *,
    name: str,
    expected_amount: int,
    next_expected_date: date,
    direction: str = "outflow",
    frequency: str = "monthly",
    owner_user_id: int = 1,
    account_id: int | None = None,
    **overrides: Any,
):
    """A hand-declared recurring stream (bill or income)."""
    kwargs: dict[str, Any] = dict(
        owner_user_id=owner_user_id,
        name=name,
        direction=direction,
        frequency=frequency,
        expected_amount=expected_amount,
        next_expected_date=next_expected_date,
        account_id=account_id,
    )
    kwargs.update(overrides)
    return await svc.create_recurring_stream(**kwargs)


async def declare_bill(
    svc: FinanceService,
    db: Any,
    account_id: int,
    name: str,
    days: list[date],
    cents: int = -1_000,
):
    """A bill the DETECTOR made: a transaction series, declared recurring.

    Returns ``(stream, txns)`` - callers that only need the side effect
    ignore the return.
    """
    from app.services.finance.domains.detection import declare_recurring

    txns = await seed_spend_series(svc, account_id, days, cents=cents, name=name)
    await declare_recurring(db, [t.id for t in txns], owner_user_id=1)
    from sqlmodel import select

    from app.services.finance.models import FinanceRecurringStream

    stream = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.deleted_at.is_(None),
                FinanceRecurringStream.name == name,
            )
        )
    ).first()
    return stream, txns


async def seed_merchant(db: Any, name: str, owner_user_id: int | None = None):
    """A payee the ledger already knows, which is one of the directories
    a letterhead is matched against.

    NULL-owner by default, because that is how this app stores them -
    every one of the 103 payees on the real ledger is global, and an
    owned row is invisible to the query that reads them.
    """
    from app.services.finance.models import FinanceMerchant

    row = FinanceMerchant(
        owner_user_id=owner_user_id,
        name=name,
        normalized_name=name.casefold(),
        source="user",
    )
    db.add(row)
    await db.flush()
    return row


# -- reading back ---------------------------------------------------------


def budget_points(result: Any, category: str) -> list[Any]:
    """A projection's draws for one category's limit. A budget point has
    no stream: a bill on the same category is not one."""
    return [p for p in result.points if p.stream_id is None and p.category == category]


class QueryCounter:
    """Counts statements hitting the database through a sync engine."""

    def __init__(self, async_engine: Any) -> None:
        self._engine = async_engine.sync_engine
        self.count = 0

    def _increment(self, *args: object, **kwargs: object) -> None:
        self.count += 1

    def __enter__(self) -> QueryCounter:
        event.listen(self._engine, "before_cursor_execute", self._increment)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._increment)
