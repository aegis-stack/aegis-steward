"""Batched read queries for the import pipeline.

Set-shaped inputs, map-shaped outputs, so callers cannot reintroduce a
per-row query loop. Statement builders only - no business logic, no
writes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

from app.services.finance.adapters.importers.base import (
    DeletedLaneRow,
    LaneRow,
    lane_columns,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceImportProfile,
    FinanceTransaction,
    FinanceTransactionChangelog,
    FinanceTransactionTag,
)
from app.services.shared.queries import owner_filters


async def account_id_by_provider_key(
    db: AsyncSession, *, account_key: str, owner_user_id: int | None
) -> int | None:
    query = select(FinanceAccount.id).where(
        FinanceAccount.provider_account_id == account_key,
        FinanceAccount.deleted_at.is_(None),
    )
    query = query.where(*owner_filters(FinanceAccount.owner_user_id, owner_user_id))
    return (await db.exec(query)).first()


def _owner_scoped_account(
    query: SelectOfScalar[Any], owner_user_id: int | None
) -> SelectOfScalar[Any]:
    if owner_user_id is not None:
        return query.where(FinanceAccount.owner_user_id == owner_user_id)
    return query.where(FinanceAccount.owner_user_id.is_(None))


async def live_account_id_by_name(
    db: AsyncSession,
    *,
    name: str,
    owner_user_id: int | None,
    account_type: str | None = None,
) -> int | None:
    query = select(FinanceAccount.id).where(
        FinanceAccount.name == name,
        FinanceAccount.deleted_at.is_(None),
    )
    if account_type is not None:
        query = query.where(FinanceAccount.account_type == account_type)
    return (await db.exec(_owner_scoped_account(query, owner_user_id))).first()


async def owner_accounts(
    db: AsyncSession, *, owner_user_id: int | None, ids: list[int] | None = None
) -> list[FinanceAccount]:
    """The owner's accounts, removed ones too, in one read (``ids`` to
    narrow it): a file's account names are matched against them all."""
    query = select(FinanceAccount)
    if ids is not None:
        query = query.where(FinanceAccount.id.in_(ids))  # type: ignore[union-attr]
    return list((await db.exec(_owner_scoped_account(query, owner_user_id))).all())


async def account_ref(db: AsyncSession, account_id: int) -> FinanceAccount | None:
    return await db.get(FinanceAccount, account_id)


async def live_transaction_lane_rows(
    db: AsyncSession, account_ids: list[int] | set[int]
) -> list[LaneRow]:
    """Every live row on the touched accounts, as lane keys.

    Columns, not entities. This is the preload that grows with the
    LEDGER rather than the file, so it is the one read in the pipeline
    that must never hydrate: see ``LaneRow``.
    """
    if not account_ids:
        return []
    rows = await db.exec(
        select(*lane_columns(LaneRow)).where(
            FinanceTransaction.account_id.in_(account_ids),
            FinanceTransaction.deleted_at.is_(None),
        )
    )
    return [LaneRow(*row) for row in rows.all()]


async def deleted_transaction_lane_rows(
    db: AsyncSession, account_ids: list[int] | set[int]
) -> list[DeletedLaneRow]:
    """Soft-deleted rows on the touched accounts - their lane keys refuse
    resurrection on re-import. Four columns; nothing reads the row."""
    if not account_ids:
        return []
    rows = await db.exec(
        select(*lane_columns(DeletedLaneRow)).where(
            FinanceTransaction.account_id.in_(account_ids),
            FinanceTransaction.deleted_at.is_not(None),
        )
    )
    return [DeletedLaneRow(*row) for row in rows.all()]


async def tag_links_for_transaction(
    db: AsyncSession, transaction_id: int
) -> list[FinanceTransactionTag]:
    return list(
        (
            await db.exec(
                select(FinanceTransactionTag).where(
                    FinanceTransactionTag.transaction_id == transaction_id
                )
            )
        ).all()
    )


async def prior_batch(
    db: AsyncSession, *, batch_owner: int, file_sha256: str
) -> FinanceImportBatch | None:
    """The batch that already ingested these exact bytes, if any."""
    return (
        await db.exec(
            select(FinanceImportBatch).where(
                FinanceImportBatch.owner_user_id == batch_owner,
                FinanceImportBatch.file_sha256 == file_sha256,
            )
        )
    ).first()


async def profile_named(db: AsyncSession, name: str) -> bool:
    """Whether a live import profile is already called ``name``."""
    found = await db.exec(
        select(FinanceImportProfile.id).where(
            FinanceImportProfile.name == name,
            FinanceImportProfile.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    )
    return found.first() is not None


async def csv_profiles(db: AsyncSession) -> list[FinanceImportProfile]:
    """The CSV layouts, yours first: one you mapped for a header (a YNAB
    file's date style, #619) is read before the seeded one for it."""
    found = await db.exec(
        select(FinanceImportProfile).where(
            FinanceImportProfile.source_format == "csv",
            FinanceImportProfile.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    )
    return sorted(found.all(), key=lambda p: (p.is_system, p.id or 0))


async def import_batch_by_id(
    db: AsyncSession, batch_id: int, *, batch_owner: int
) -> FinanceImportBatch | None:
    return (
        await db.exec(
            select(FinanceImportBatch).where(
                FinanceImportBatch.id == batch_id,
                FinanceImportBatch.owner_user_id == batch_owner,
            )
        )
    ).first()


async def import_batches_page(
    db: AsyncSession, *, batch_owner: int, page: int, page_size: int
) -> list[FinanceImportBatch]:
    query = (
        select(FinanceImportBatch)
        .where(FinanceImportBatch.owner_user_id == batch_owner)
        .order_by(FinanceImportBatch.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.exec(query)).all())


async def import_batch_rows(
    db: AsyncSession, batch_id: int
) -> list[FinanceImportBatchRow]:
    query = (
        select(FinanceImportBatchRow)
        .where(FinanceImportBatchRow.import_batch_id == batch_id)
        .order_by(FinanceImportBatchRow.row_number)
    )
    return list((await db.exec(query)).all())


async def batch_row_ids(db: AsyncSession, batch_id: int) -> dict[str, set[int]]:
    """The transactions one batch added and changed, by row status: two
    columns, not the 18,000 parsed rows (#621)."""
    rows = await db.exec(
        select(
            FinanceImportBatchRow.parsed_status,
            FinanceImportBatchRow.matched_transaction_id,
        ).where(
            FinanceImportBatchRow.import_batch_id == batch_id,
            FinanceImportBatchRow.parsed_status.in_(("inserted", "updated")),  # type: ignore[attr-defined]
            FinanceImportBatchRow.matched_transaction_id.is_not(None),  # type: ignore[union-attr]
        )
    )
    found: dict[str, set[int]] = {"inserted": set(), "updated": set()}
    for status, transaction_id in rows.all():
        found[status].add(transaction_id)
    return found


def added_by(batch_id: int) -> Any:
    """The ids a batch added, as a subquery: no list to bind."""
    return select(FinanceImportBatchRow.matched_transaction_id).where(
        FinanceImportBatchRow.import_batch_id == batch_id,
        FinanceImportBatchRow.parsed_status == "inserted",
    )


async def edited_since(
    db: AsyncSession, batch_id: int, since: Any, by_arrivals: frozenset[str] | set[str]
) -> set[int]:
    """Rows a batch added that a person has edited since (#621)."""
    rows = await db.exec(
        select(FinanceTransactionChangelog.transaction_id)
        .where(
            FinanceTransactionChangelog.transaction_id.in_(added_by(batch_id)),  # type: ignore[attr-defined]
            FinanceTransactionChangelog.changed_at >= since,
            FinanceTransactionChangelog.change_source.not_in(by_arrivals),  # type: ignore[attr-defined]
            FinanceTransactionChangelog.undone_at.is_(None),  # type: ignore[union-attr]
        )
        .distinct()
    )
    return set(rows.all())


async def forget_identity(db: AsyncSession, batch_id: int, *, keep: set[int]) -> None:
    """Clear the FITID and hash on what a batch added (bar ``keep``), so
    the planner does not read an undone row as one you deleted (#621)."""
    await db.exec(
        update(FinanceTransaction)
        .where(
            FinanceTransaction.id.in_(added_by(batch_id)),  # type: ignore[union-attr]
            FinanceTransaction.id.not_in(keep),  # type: ignore[union-attr]
        )
        .values(external_id=None, import_hash=None)
    )
