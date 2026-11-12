"""Which of your accounts a file's account name is (#620).

A multi-account export names accounts its own way: Monarch writes
``Signature Visa (...2562)``, Empower ``Platinum Card - Ending in 1002``.
A name the ledger has (an account's own, or one you answered for before)
routes its rows; any other is asked about before Import, with the account
sharing its last four suggested. The answer is kept on the account, so
the next file from the same app routes without asking.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import queries
from app.services.finance.domains.ledger.numbers import MASK_DIGITS, last_four
from app.services.finance.models import FinanceAccount

# Where an account keeps the names files have called it.
NAMES = "import_names"


def means(account: FinanceAccount, name: str) -> bool:
    """Whether a file's name is this account: its own, or one kept."""
    return account.name == name or name in (account.metadata_ or {}).get(NAMES, [])


def known(live: list[FinanceAccount], name: str) -> FinanceAccount | None:
    """The live account this name already means. An account's own name
    wins over a name another account was answered for."""
    own = next((a for a in live if a.name == name), None)
    return own or next((a for a in live if means(a, name)), None)


def choices(live: list[FinanceAccount]) -> list[tuple[int, str]]:
    """Your live accounts as an answer can pick them, (id, name) by name."""
    return sorted(((a.id, a.name) for a in live if a.id), key=lambda c: c[1])


def suggest(live: list[FinanceAccount], name: str) -> int | None:
    """The one live account sharing the name's last four, if exactly one."""
    four = last_four(name)
    matches = [a.id for a in live if four and a.mask and a.mask[-MASK_DIGITS:] == four]
    return matches[0] if len(matches) == 1 else None


async def remember(
    db: AsyncSession, answers: dict[str, int], *, owner_user_id: int | None
) -> None:
    """Keep each answer on its account: the name a file used for it."""
    ids = sorted(set(answers.values()))
    accounts = {
        a.id: a
        for a in await queries.owner_accounts(db, owner_user_id=owner_user_id, ids=ids)
        if a.deleted_at is None
    }
    if set(ids) - accounts.keys():
        raise LookupError("An answer names an account that is not yours.")
    for name, account_id in answers.items():
        account = accounts[account_id]
        names = (account.metadata_ or {}).get(NAMES, [])
        if name not in names:
            # A new dict, not a mutation: the JSON column sees a whole value.
            account.metadata_ = {**(account.metadata_ or {}), NAMES: [*names, name]}
            db.add(account)
    await db.flush()
