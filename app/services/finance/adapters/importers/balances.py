"""What a file says its accounts hold, after its rows land (#622).

A register file's last running balance becomes the account's balance, so
net worth reflects the import with no separate valuation. Every balance
the file states - that one, an OFX statement's ledger balance - then
checks the register on its date, the check a filed statement gets
(#321): a gap is named on the done screen and on Attention, with Correct
the balance filled in; a match reconciles the account through that date.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import queries
from app.services.finance.adapters.importers.base import (
    ParsedTransaction,
    StatementBalance,
    _is_posted,
)
from app.services.finance.domains.detection.insights.statement_gaps import (
    check_statement,
)
from app.services.finance.domains.ledger.accounts import statement_balance
from app.services.finance.schemas.imports import BalanceCheck
from app.services.finance.utils import current_date


def _running_ending(
    parsed: Sequence[ParsedTransaction],
) -> StatementBalance | None:
    """The file's last posted running balance. Posted rows only: a
    scheduled row's running balance is a PROJECTED figure, and taking it
    as the account's real balance would book money that has not moved."""
    today = current_date()
    balanced = [
        (txn.date, i, txn.running_balance)
        for i, txn in enumerate(parsed)
        if _is_posted(txn, today) and txn.running_balance is not None
    ]
    if not balanced:
        return None
    ending_date, _, ending = max(balanced)
    return StatementBalance(None, ending_date, ending)


async def settle_balances(
    db: AsyncSession,
    *,
    parsed: Sequence[ParsedTransaction],
    stated: Sequence[StatementBalance],
    route: dict[str | None, int],
    account_id: int | None,
) -> list[BalanceCheck]:
    """Each account's latest stated balance against its register.
    ``route`` maps an account key to the account its rows went to;
    ``account_id``, the one picked, takes every balance - and a register
    file's last running balance becomes its own."""
    stated = list(stated)
    running = _running_ending(parsed)
    if account_id is not None and running is not None:
        account = await queries.account_ref(db, account_id)
        if account is not None:
            account.current_balance = running.amount
            account.balance_as_of = datetime(
                running.as_of.year, running.as_of.month, running.as_of.day
            )
            db.add(account)
        stated.append(running)
    latest: dict[int, StatementBalance] = {}
    for balance in stated:
        target = (
            account_id if account_id is not None else route.get(balance.account_key)
        )
        if target is not None and (
            target not in latest or balance.as_of >= latest[target].as_of
        ):
            latest[target] = balance
    checks: list[BalanceCheck] = []
    # ponytail: one account at a time, as a filed statement is checked; a
    # file names a handful. Batch check_statement if one ever names many.
    for target, balance in latest.items():
        account = await queries.account_ref(db, target)
        if account is None or account.id is None:
            continue
        printed = statement_balance(account.classification, balance.amount)
        gap = await check_statement(
            db, account, statement_date=balance.as_of, printed=printed
        )
        checks.append(
            BalanceCheck(
                account_id=account.id,
                account_name=account.name,
                as_of=balance.as_of,
                printed=printed,
                gap=gap,
            )
        )
    return checks
