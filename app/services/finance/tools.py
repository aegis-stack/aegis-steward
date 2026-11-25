"""Finance host tools: the data surface code-mode agents compute over.

Deliberately few and wide: results land in the code-mode sandbox rather
than the prompt, so a broad payload the model slices in code beats a
catalog of narrow question-shaped tools. Each tool is a thin, fully-typed
composition of existing domain queries, registered into the agent tool
registry at import time. A code-mode agent granted these names calls them
as functions from inside its sandboxed script; a plain agent calls them
as ordinary tools.

Returns are plain JSON-safe dicts (cents-integer money, ISO dates) so
values traverse the sandbox boundary without model-object baggage.

Owner scoping: tools read unscoped (``owner_user_id=None``), matching
the single-tenant default-open posture of generated stacks. A
multi-tenant deployment should thread its user context here before
granting these tools to shared agents.
"""

from datetime import date
from typing import Any, Literal, overload

from app.core.db import get_async_session
from app.core.formatting import payee_label
from app.core.tools import register_tool
from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES

# The memory-module fetchers register where the tools do, so every
# process that can run her (chat, MCP, the CLI's test turn) has them.
from app.services.finance.domains.detection.analyst import report  # noqa: F401
from app.services.finance.domains.investments import queries as investment_queries
from app.services.finance.domains.ledger.cash_flow import month_review
from app.services.finance.domains.ledger.queries.accounts import EVERYONE, accounts_page
from app.services.finance.domains.ledger.queries.categories import (
    category_named,
    category_names_by_id,
)
from app.services.finance.domains.ledger.queries.flows import counted_as
from app.services.finance.domains.ledger.queries.transactions import (
    transactions_window_with_payees,
)
from app.services.finance.domains.ledger.transactions import (
    transaction_tags,
)
from app.services.finance.schemas import agent_tools as shapes
from app.services.finance.utils import (
    current_date,
    month_start_before,
)

# Sized for years of a personal ledger (a few thousand rows/year); rows
# land in the code-mode sandbox, not the model's context, so the cost of
# a big window is a few ms of marshaling. ``total`` in the payload still
# exposes truncation, so a capped result never reads as complete.
_TRANSACTIONS_ROW_CAP = 5000

# How far ahead accounts() reports scheduled flows: one full monthly
# cycle with margin, so a mid-month plan sees next month's rent.
_UPCOMING_WINDOW_DAYS = 35
# Monthly detail, or the rows (``detail``); the overloads say which.
Ledger = shapes.LedgerMonths | shapes.Transactions


# What the monthly figures count, said with them (#294): two reviews a day
# apart reported September as $13,635 and as $1,372, with no scope given.
LEDGER_SCOPE = (
    "Money in and out of every account tracked, all spending (bills "
    "included); transfers between your own accounts and rows excluded "
    "from reports are left out. Income is what is filed as income; a "
    "refund nets against the category it is filed under; a credit filed "
    "as nothing is in neither and counted apart as unfiled."
)


@overload
async def ledger(
    months: int = 12, detail: Literal["monthly"] = "monthly"
) -> shapes.LedgerMonths: ...
@overload
async def ledger(
    months: int = 12, *, detail: Literal["transactions"]
) -> shapes.Transactions: ...
@overload
async def ledger(months: int = 12, detail: str = "monthly") -> Ledger: ...


async def ledger(months: int = 12, detail: str = "monthly") -> Ledger:
    """Cash flow from the transaction ledger.

    Args:
        months: How many months back to include (1-24).
        detail: "monthly" or "transactions".

    Monthly detail returns 'scope' (what is counted - say it when you
    report a figure), 'months': a list, oldest first, of entries carrying
    'month', 'income_cents', 'spend_cents', 'net_cents' and
    'unfiled_cents' (credits filed as nothing, in neither figure - name
    it when it is big enough to change the picture; the current month is
    only so far), and
    'month_to_date': 'through_day', and 'this_month' beside
    'last_month_same_days' (each 'income', 'spending', 'unfiled', 'saved'
    in cents). Compare a part-finished month with
    'last_month_same_days', never with last month's whole total. Transaction detail returns keys 'total', 'returned'
    and 'transactions': a list, newest first, of rows shaped as
    ``transactions`` returns them ('amount_cents' signed, negative =
    outflow); fewer returned rows than 'total' means the page was capped.
    """
    if detail == "monthly":
        span = max(1, min(int(months), 24))
        async with get_async_session() as session:
            rows, so_far = await month_review(
                session, owner_user_id=None, months=span, today=current_date()
            )
        return {
            "scope": LEDGER_SCOPE,
            "month_to_date": so_far.model_dump(),
            "months": [
                {
                    "month": row.month,
                    "income_cents": row.income,
                    "spend_cents": row.expense,
                    "net_cents": row.net,
                    "unfiled_cents": row.unfiled,
                }
                for row in rows
            ],
        }
    if detail != "transactions":
        raise ValueError('detail must be "monthly" or "transactions"')

    span = max(1, min(int(months), 24))
    from_date = month_start_before(current_date(), span - 1)
    async with get_async_session() as session:
        rows, total = await transactions_window_with_payees(
            session,
            from_date=from_date,
            limit=_TRANSACTIONS_ROW_CAP,
        )
        items = await transaction_rows(session, rows)
    return _found(total, items)


async def transaction_rows(
    session: Any, rows: list[tuple[Any, str | None]]
) -> list[shapes.TransactionRow]:
    """A transaction as the agent reads it, whichever tool found it: one
    shape, so a field added reaches every tool (``bill_id`` once reached
    ``transactions`` and not ``ledger``, #460). ``rows`` pairs each with
    its curated payee name, or None."""
    category_names = await category_names_by_id(
        session, {t.category_id for t, _name in rows if t.category_id is not None}
    )
    account_rows, _count = await accounts_page(
        session,
        owner_user_id=None,
        include_hidden=True,
        page=1,
        page_size=500,
        subject_id=EVERYONE,
        include_closed=True,
    )
    account_names = {account.id: account.name for account in account_rows}
    ids = [t.id for t, _name in rows if t.id is not None]
    tags_by_txn = await transaction_tags(session, ids)
    kinds = await counted_as(session, ids)
    return [
        {
            # The id is what a transaction.categorize proposal's
            # 'transaction_id' takes - names alone cannot propose.
            "id": txn.id,
            "date": txn.date_.isoformat(),
            # Curated merchant name first - what the register shows -
            # then the provider's merchant string, then the raw
            # descriptor. A renamed payee that only lived in the
            # curation layer was invisible to the assistant.
            "payee": payee_label(curated_name, txn.merchant_name, txn.name),
            "amount_cents": txn.amount,
            "category": category_names.get(txn.category_id),
            "category_id": txn.category_id,
            # True for BOTH shapes of uncategorized: no category at
            # all, or the import catch-all bucket ("Uncategorized",
            # "Misc", ...). Filtering category is None alone misses
            # the second shape - a model burned four runs on that.
            "uncategorized": txn.category_id is None
            or (category_names.get(txn.category_id) or "").lower()
            in UNCATEGORIZED_CATEGORY_NAMES,
            "account": account_names.get(txn.account_id),
            # The label axis, orthogonal to category ("Business" on
            # a Software row) - what tag rollups compute over.
            "tags": sorted(t.name for t in tags_by_txn.get(txn.id, [])),
            "memo": txn.memo,
            "transfer": txn.is_transfer,
            "counts_as": kinds.get(txn.id or 0),  # as every total does (#316)
            "pending": txn.pending,
            # The bill (``bills``' id) the row is already matched to.
            "bill_id": txn.recurring_stream_id,
        }
        for txn, curated_name in rows
    ]


async def quote(ticker: str) -> shapes.Quote:
    """Latest stored closing price for a ticker in the security catalog.

    Args:
        ticker: The security's ticker symbol, case-insensitive.
    """
    symbol = ticker.strip().upper()
    async with get_async_session() as session:
        security = await investment_queries.security_by_ticker(session, symbol)
        if security is None or security.id is None:
            return {"found": False, "ticker": symbol}
        price = await investment_queries.latest_price_for_security(session, security.id)
    if price is None:
        return {"found": False, "ticker": symbol}
    # Normalize to cents in integer arithmetic regardless of the row's
    # stored scale; float exponents would drift on sub-cent scales.
    if price.price_scale > 2:
        divisor = 10 ** (price.price_scale - 2)
        close_cents = (price.close_price + divisor // 2) // divisor
    else:
        close_cents = price.close_price * 10 ** (2 - price.price_scale)
    as_of: date = price.price_date
    return {
        "found": True,
        "ticker": symbol,
        "name": security.name,
        "close_cents": close_cents,
        "as_of": as_of.isoformat(),
    }


# Built-in registration: importing this module makes the tools grantable
# via the agent registry. replace=True keeps re-imports idempotent.


async def projection(
    days: int = 180,
    account_ids: list[int] | None = None,
) -> shapes.Projection:
    """Cash walked forward from today through the scheduled bills and
    income, over any window: 'as_of', 'horizon_days',
    'start_balance_cents', 'end_balance_cents', 'upcoming_total_cents'
    (signed, net of the window), 'bills' (what is due, positive
    'amount_cents', soonest first) and 'points' (every occurrence with its
    signed 'amount_cents' and the running 'balance_cents' after it, so the
    low point and the date it happens are read off the walk rather than
    re-derived).

    ``days`` is the window - 365 for a year, 30 for the month - and
    ``account_ids`` narrows the starting balance to particular accounts
    ("only the checking, not savings"). Without this the only
    forward-looking number available was the fixed 60-day figure in the
    briefing, so any other horizon had to be hand-rolled from the bill
    list and then disowned as untrustworthy.

    "What bills are due this week?" is ONE script, and this is it:

        due = await projection(days=7)
        print(due["upcoming_total_usd"], due["bills"])

    The answer is what it prints: never read ``bills()`` for it. A bill's
    stored 'next_expected_date' can be long past; the walk here already
    dates each one in the window.
    """
    from app.services.finance.domains.planning.recurring.forecast import (
        project_balances,
        upcoming_outflows,
    )

    async with get_async_session() as session:
        walk = await project_balances(
            session, owner_user_id=None, days=days, account_ids=account_ids
        )
    return {
        "as_of": walk.as_of.isoformat(),
        "horizon_days": walk.horizon_days,
        "start_balance_cents": walk.start_balance,
        "end_balance_cents": walk.end_balance,
        "upcoming_total_cents": walk.upcoming_total,
        "bills": [
            {
                "name": bill["name"],
                "date": bill["date"].isoformat(),
                "due_date": bill["due_date"].isoformat() if bill["due_date"] else None,
                "amount_cents": bill["amount"],
                "category": bill["category"],
                "bill_id": bill["bill_id"],
            }
            for bill in upcoming_outflows(walk)
        ],
        "points": [
            {
                "date": p.date.isoformat(),
                "name": p.name,
                "direction": p.direction,
                "amount_cents": p.amount,
                "balance_cents": p.balance,
                "account": p.account,
                "category": p.category,
                "bill_id": p.stream_id,  # ``bills``' id; null for a non-bill point
            }
            for p in walk.points
        ],
    }


async def transactions(
    payee: str | None = None,
    amount_cents: int | None = None,
    since: str | None = None,
    until: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    category: str | None = None,
) -> shapes.Transactions:
    """Find PARTICULAR transactions, without reading the ledger.

    Every filter is optional and they narrow together: ``payee`` matches
    the payee or the raw descriptor, ``amount_cents`` matches by
    magnitude (800 finds a $8.00 charge whichever way it is signed),
    ``since``/``until`` are ISO dates, ``tag`` is a tag's name (a year of
    "Tax Related" is one call), ``category`` a category's name, whole or
    its last part ("Groceries": a month of it is one call). Returns 'total' (how many match) and
    'transactions' - id, date, payee, amount_cents, category,
    category_id, uncategorized (no category, or a catch-all bucket), tags,
    account, memo, transfer, counts_as, pending, bill_id - newest first,
    capped at ``limit``: 'returned' below 'total' means more match, so ask
    for a higher limit, not for halves. 'summary' is what those rows add
    up to: spending (charges less credits), income, and spending by payee
    and by category. "What did groceries cost last month?" is ONE script:

        found = await transactions(category="Groceries", since=..., until=...)
        print(found["summary"])

    and the answer is in what it prints: never sum or group the rows in a
    second run, and never total a payee yourself.
    'counts_as' is what every total counts it as: income, spending (signed:
    a credit here lowers spending by its amount, whatever its payee), unfiled,
    transfer, split (by its lines) or not counted. Total by it, not by sign.
    'tags' is what the row wears now: read it before proposing a tag.
    'bill_id' is the bill (``bills``' id) the row is already matched to,
    or null.

    It finds every row, transfers included. ``transfer: true`` means the
    row is flagged as money between accounts: hidden from the register
    unless "Show transfers" is on, and left out of spending. A payment
    wrongly flagged (a mortgage or a nursing home categorized "Transfer")
    is fixed by recategorizing it to a spending category, which clears
    the flag - unless it is paired with a deposit on another account.

    Use this, not ``ledger(detail="transactions")``, whenever the
    question names a payee, an amount or a date: matching a receipt to
    a charge used to mean pulling months of ledger into the sandbox and
    filtering in Python, which is slow, easy to get wrong, and pulled
    two years of rows to find three. ``ledger`` is for the SHAPE of
    spending; this is for the rows.
    """
    from app.services.finance.service import FinanceService

    def _date(raw: str | None) -> date | None:
        return date.fromisoformat(raw) if raw else None

    async with get_async_session() as session:
        tag_id = None
        if tag:
            from app.services.finance.domains.ledger.transactions import list_tags

            known = {
                t.name.casefold(): t
                for t, _count in await list_tags(session, owner_user_id=None)
            }
            if (found := known.get(tag.strip().casefold())) is None:
                names = ", ".join(sorted(t.name for t in known.values()))
                return _none_found(f"No tag is called {tag!r}. Tags: {names}.")
            tag_id = found.id
        category_id = None
        if category:
            picked, near = await category_named(session, category)
            if picked is None:
                held = ", ".join(near) or "none"
                return _none_found(
                    f"No one category is {category!r}. Holding it: {held}."
                )
            category_id = picked.id
        service = FinanceService(session)
        rows, total = await service.list_transactions(
            owner_user_id=None,
            query=payee or None,
            amount=amount_cents,
            from_date=_date(since),
            to_date=_date(until),
            tag_id=tag_id,
            category_id=category_id,
            page_size=max(1, min(int(limit), _TRANSACTIONS_ROW_CAP)),
            # A search hides nothing: the register's default hid Dad's
            # mortgage from her, and she called it "already" right (#278).
            include_transfers=True,
        )
        payees = await service.merchant_names(
            {t.merchant_id for t in rows if t.merchant_id is not None}
        )
        items = await transaction_rows(
            session, [(t, payees.get(t.merchant_id)) for t in rows]
        )
    return _found(total, items)


def _none_found(error: str) -> shapes.Transactions:
    """A filter that names nothing: said, so she corrects it (``error``)."""
    return {**_found(0, []), "error": error}


def _found(total: int, rows: list[shapes.TransactionRow]) -> shapes.Transactions:
    """Rows with their figures (``TransactionsSummary``): every extra run
    she made was one of these sums, and a payee total she wrote herself
    was wrong."""
    charges = credits = income = 0
    by_payee: dict[str, int] = {}
    by_category: dict[str, int] = {}
    other: dict[str, int] = {}
    for row in rows:
        kind, cents = row["counts_as"] or "not counted", row["amount_cents"]
        if kind == "income":
            income += cents
        elif kind == "spending":
            charges, credits = charges + max(-cents, 0), credits + max(cents, 0)
            payee, category = row["payee"] or "(no payee)", row["category"] or "(none)"
            by_payee[payee] = by_payee.get(payee, 0) - cents
            by_category[category] = by_category.get(category, 0) - cents
        else:
            other[kind] = other.get(kind, 0) + 1
    return {
        "total": total,
        "returned": len(rows),
        "transactions": rows,
        "summary": {
            "complete": len(rows) >= total,
            "spending_cents": charges - credits,
            "charges_cents": charges,
            "credits_cents": credits,
            "income_cents": income,
            "by_payee": dict(sorted(by_payee.items(), key=lambda kv: -kv[1])),
            "by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
            "not_in_spending": other,
        },
    }


for name, func, description in (
    ("ledger", ledger, "Cash flow: monthly rollups or individual transactions"),
    (
        "transactions",
        transactions,
        "Find particular transactions by payee, amount or date",
    ),
    (
        "projection",
        projection,
        "Cash walked forward through scheduled bills over any window",
    ),
    ("quote", quote, "Latest stored closing price for a ticker"),
):
    register_tool(name, func, description=description, effect="read", replace=True)

# The balance sheet and the write-side tools live in their own modules;
# importing them here keeps "import tools" the one line that
# registers the whole finance tool surface.
from app.services.finance.ai_account_tools import accounts  # noqa: E402,F401
from app.services.finance.ai_bill_tools import bill_candidates, bills  # noqa: E402,F401
from app.services.finance.ai_budget_tools import budget  # noqa: E402,F401
from app.services.finance.ai_write_tools import categories, tags  # noqa: E402,F401
from app.services.finance.domains.ledger.cleanup import (  # noqa: E402,F401
    cleanup_candidates,
)
from app.services.finance.domains.planning.retirement_tool import (  # noqa: E402,F401
    retirement,
)
