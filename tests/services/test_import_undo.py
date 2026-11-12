"""Undo an import (#621): one batch taken back as a whole.

What the batch added goes, what it changed goes back, and a row someone
edited since it landed is kept: that edit is a decision the import did
not make.
"""

from pathlib import Path

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import imports, undo
from app.services.finance.adapters.importers.base import ParsedTransaction
from app.services.finance.adapters.importers.ofx import parse_ofx
from app.services.finance.adapters.importers.qif import parse_qif
from app.services.finance.domains.ledger import changelog
from app.services.finance.models import FinanceAccount, FinanceImportBatch
from app.services.finance.service import FinanceService

_FIXTURES = Path(__file__).parent / "finance" / "fixtures"


async def _account(session: AsyncSession) -> FinanceAccount:
    return await FinanceService(session).create_manual_account(
        owner_user_id=1,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
    )


async def _ingest(
    session: AsyncSession, account: FinanceAccount, data: bytes, name: str = "c.qfx"
) -> imports.ImportResult:
    return await imports.ingest_transactions(
        session,
        owner_user_id=1,
        source_type="qfx",
        file_name=name,
        file_bytes=data,
        parsed=parse_ofx(data, source="qfx"),
        default_account_id=account.id,
    )


async def _batch(
    session: AsyncSession, result: imports.ImportResult
) -> FinanceImportBatch:
    batch = await session.get(FinanceImportBatch, result.batch_id)
    assert batch is not None
    return batch


@pytest.mark.asyncio
async def test_undo_removes_what_the_import_added(
    svc: FinanceService, async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    data = (_FIXTURES / "sample_chase.qfx").read_bytes()
    batch = await _batch(
        async_db_session, await _ingest(async_db_session, account, data)
    )

    taken = await undo.undo_import(async_db_session, batch, owner_user_id=1)

    assert (taken.removed, taken.restored, taken.kept) == (6, 0, 0)
    _, total = await svc.list_transactions(owner_user_id=1, account_id=account.id)
    assert total == 0
    assert batch.status == "rolled_back"


@pytest.mark.asyncio
async def test_the_same_file_imports_again_after_an_undo(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    data = (_FIXTURES / "sample_chase.qfx").read_bytes()
    first = await _ingest(async_db_session, account, data)
    await undo.undo_import(
        async_db_session, await _batch(async_db_session, first), owner_user_id=1
    )

    again = await _ingest(async_db_session, account, data)

    assert again.batch_id != first.batch_id
    assert again.rows_inserted == 6


@pytest.mark.asyncio
async def test_undo_puts_back_what_the_import_changed(
    svc: FinanceService, async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    data = (_FIXTURES / "sample_quicken.qif").read_bytes()
    await imports.ingest_transactions(
        async_db_session,
        owner_user_id=1,
        source_type="qif",
        file_name="q.qif",
        file_bytes=data,
        parsed=parse_qif(data, source="qif"),
        default_account_id=account.id,
    )
    before, _ = await svc.list_transactions(owner_user_id=1, account_id=account.id)
    target = before[0]
    original_name, original_memo = target.name, target.memo
    edit = await imports.ingest_transactions(
        async_db_session,
        owner_user_id=1,
        source_type="qif",
        file_name="q2.qif",
        file_bytes=b"different bytes",
        parsed=[
            ParsedTransaction(
                date=target.date_,
                amount=target.amount,
                name="RENAMED BY THE FILE",
                source="qif",
                memo="memo from the file",
            )
        ],
        default_account_id=account.id,
    )
    assert edit.rows_updated == 1

    taken = await undo.undo_import(
        async_db_session, await _batch(async_db_session, edit), owner_user_id=1
    )

    assert (taken.removed, taken.restored) == (0, 2)  # name and memo
    await async_db_session.refresh(target)
    assert (target.name, target.memo) == (original_name, original_memo)
    # Redo puts back what you or an assistant undid; an import is taken
    # back whole, so half of one is never offered again.
    assert await changelog.last_redoable(async_db_session, 1) is None


@pytest.mark.asyncio
async def test_a_row_edited_since_the_import_is_kept(
    svc: FinanceService, async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    data = (_FIXTURES / "sample_chase.qfx").read_bytes()
    result = await _ingest(async_db_session, account, data)
    rows, _ = await svc.list_transactions(owner_user_id=1, account_id=account.id)
    with changelog.acting("you"):
        rows[0].memo = "mine now"
        async_db_session.add(rows[0])
        await async_db_session.flush()

    taken = await undo.undo_import(
        async_db_session, await _batch(async_db_session, result), owner_user_id=1
    )

    assert (taken.removed, taken.kept) == (5, 1)
    left, total = await svc.list_transactions(owner_user_id=1, account_id=account.id)
    assert total == 1 and left[0].id == rows[0].id


@pytest.mark.asyncio
async def test_only_a_committed_file_import_can_be_undone(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    account = await _account(async_db_session)
    data = (_FIXTURES / "sample_chase.qfx").read_bytes()
    result = await _ingest(async_db_session, account, data)
    batch = await _batch(async_db_session, result)
    await undo.undo_import(async_db_session, batch, owner_user_id=1)

    with pytest.raises(ValueError, match="cannot be undone"):
        await undo.undo_import(async_db_session, batch, owner_user_id=1)
