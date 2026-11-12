"""After an import, the file's balances check the ledger (#622).

Nothing said whether the ledger agreed with the bank once a file landed.
Now each balance the file states (an OFX statement's ledger balance, a
register file's last running balance) is compared with the register on
its date, the check a filed statement already gets (#321): a gap is named
on the result and on Attention, a match reconciles the account.
"""

from datetime import date
from pathlib import Path

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import imports
from app.services.finance.models import FinanceAccount, FinanceInsight
from app.services.finance.service import FinanceService

_FIXTURES = Path(__file__).parent / "finance" / "fixtures"
# sample_chase.qfx: six rows that sum to 2,909.71, a ledger balance of 5,000.
_CHASE = (_FIXTURES / "sample_chase.qfx").read_bytes()


async def _account(session: AsyncSession) -> FinanceAccount:
    return await FinanceService(session).create_manual_account(
        owner_user_id=1,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
    )


async def _import(
    session: AsyncSession, account: FinanceAccount, data: bytes, name: str
) -> imports.ImportResult:
    return await imports.import_file(
        session,
        owner_user_id=1,
        file_name=name,
        file_bytes=data,
        account_id=account.id,
    )


@pytest.mark.asyncio
async def test_a_balance_the_ledger_disagrees_with_is_named(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    result = await _import(async_db_session, account, _CHASE, "c.qfx")
    assert result.balances is not None
    [check] = result.balances
    assert (check.account_id, check.as_of, check.printed) == (
        account.id,
        date(2026, 7, 6),
        500000,
    )
    assert check.gap == 500000 - 290971
    gaps = (
        await async_db_session.exec(
            select(FinanceInsight).where(FinanceInsight.insight_type == "statement_gap")
        )
    ).all()
    assert [g.related_account_id for g in gaps] == [account.id]


@pytest.mark.asyncio
async def test_a_balance_that_agrees_reconciles_the_account(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    agrees = _CHASE.replace(b"<BALAMT>5000.00", b"<BALAMT>2909.71")
    result = await _import(async_db_session, account, agrees, "c.qfx")
    assert result.balances is not None
    assert [c.gap for c in result.balances] == [0]
    assert (account.metadata_ or {}).get("reconciled_through") == "2026-07-06"


@pytest.mark.asyncio
async def test_a_register_files_last_running_balance_is_checked(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    data = (_FIXTURES / "sample_quicken_mac.csv").read_bytes()
    result = await _import(async_db_session, account, data, "quicken.csv")
    assert result.balances is not None
    [check] = result.balances
    assert (check.as_of, check.printed) == (date(2026, 7, 3), 592535)
    # And the account still takes that balance as its own, as it did.
    assert account.current_balance == 592535


@pytest.mark.asyncio
async def test_a_file_with_no_balances_says_so(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    qif = b"!Type:Bank\nD07/01/2026\nT-4.75\nPCoffee\n^\n"
    result = await _import(async_db_session, account, qif, "c.qif")
    assert result.balances == []
