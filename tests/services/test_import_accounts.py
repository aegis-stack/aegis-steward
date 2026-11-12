"""One question per account name the ledger does not know (#620); the
rule is in ``importers/account_names``."""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import account_names
from app.services.finance.adapters.importers.base import ParsedTransaction
from app.services.finance.adapters.importers.plan import plan_transactions
from app.services.finance.models import FinanceAccount
from app.services.finance.service import FinanceService

KEY = "Signature Visa (...2562)"


def _rows(key: str = KEY) -> list[ParsedTransaction]:
    return [
        ParsedTransaction(
            date=date(2026, 3, d),
            amount=-475,
            name="Cafe",
            source="csv",
            account_key=key,
        )
        for d in (2, 9)
    ]


async def _account(
    db: AsyncSession, name: str, mask: str | None = None
) -> FinanceAccount:
    account = await FinanceService(db).create_manual_account(
        owner_user_id=None,
        name=name,
        account_type="credit_card",
        classification="liability",
    )
    account.mask = mask
    db.add(account)
    await db.flush()
    return account


async def _plan(db: AsyncSession, key: str = KEY):  # type: ignore[no-untyped-def]
    return await plan_transactions(
        db, owner_user_id=None, parsed=_rows(key), auto_create_accounts=True
    )


@pytest.mark.asyncio
async def test_a_name_the_ledger_does_not_know_is_asked_with_its_last_four(
    async_db_session: AsyncSession,
) -> None:
    await _account(async_db_session, "Checking", "4156")
    card = await _account(async_db_session, "Chase Sapphire", "2562")

    plan = await _plan(async_db_session)

    [question] = plan.account_questions
    assert (question.key, question.suggested_id, question.rows) == (KEY, card.id, 2)
    assert (question.date_start, question.date_end) == (
        date(2026, 3, 2),
        date(2026, 3, 9),
    )


@pytest.mark.asyncio
async def test_an_answer_is_kept_for_the_next_file(
    async_db_session: AsyncSession,
) -> None:
    card = await _account(async_db_session, "Chase Sapphire", "2562")

    await account_names.remember(async_db_session, {KEY: card.id}, owner_user_id=None)
    plan = await _plan(async_db_session)

    assert plan.account_questions == []
    assert plan.account_by_key[KEY] == card.id
    assert plan.new_accounts == {}


@pytest.mark.asyncio
async def test_a_name_kept_for_a_removed_account_stays_out(
    async_db_session: AsyncSession,
) -> None:
    """Removing an account is a standing no, for the names it was
    answered for too: its rows are ignored, not asked about again."""
    await _account(async_db_session, "Checking")
    card = await _account(async_db_session, "Chase Sapphire")
    await account_names.remember(async_db_session, {KEY: card.id}, owner_user_id=None)
    await FinanceService(async_db_session).soft_delete_account(card.id)

    plan = await _plan(async_db_session)

    assert (plan.account_questions, plan.removed_accounts) == ([], [KEY])


@pytest.mark.asyncio
async def test_an_accounts_own_name_wins_over_one_kept_for_another(
    async_db_session: AsyncSession,
) -> None:
    other = await _account(async_db_session, "Chase Sapphire")
    await account_names.remember(async_db_session, {KEY: other.id}, owner_user_id=None)
    own = await _account(async_db_session, KEY)

    assert (await _plan(async_db_session)).account_by_key[KEY] == own.id


@pytest.mark.asyncio
async def test_a_name_the_ledger_already_has_is_not_asked(
    async_db_session: AsyncSession,
) -> None:
    card = await _account(async_db_session, KEY)
    plan = await _plan(async_db_session)
    assert plan.account_questions == []
    assert plan.account_by_key[KEY] == card.id


@pytest.mark.asyncio
async def test_with_no_accounts_yet_there_is_nothing_to_ask(
    async_db_session: AsyncSession,
) -> None:
    plan = await _plan(async_db_session)
    assert plan.account_questions == []
    assert KEY in plan.new_accounts


@pytest.mark.asyncio
async def test_an_answer_for_someone_elses_account_is_refused(
    async_db_session: AsyncSession,
) -> None:
    other = await FinanceService(async_db_session).create_manual_account(
        owner_user_id=7, name="Theirs", account_type="checking", classification="asset"
    )
    with pytest.raises(LookupError):
        await account_names.remember(async_db_session, {KEY: other.id}, owner_user_id=1)


@pytest.mark.parametrize(
    ("name", "four"),
    [
        ("Signature Visa (...2562)", "2562"),
        ("Platinum Card - Ending in 1002", "1002"),
        ("Credit Card 2637", "2637"),
        ("Joint Checking", None),
    ],
)
def test_the_last_four_a_name_carries(name: str, four: str | None) -> None:
    assert account_names.last_four(name) == four
