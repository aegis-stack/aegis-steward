"""Undo an import (#621): one file's batch taken back as a whole.

Plain Undo never reaches an import (``changelog.NOT_UNDOABLE``): an
arrival is history, and the last thing you did should not be a file that
landed after it. Taking a wrong file back is its own, named act, on the
batch the file made:

- rows it ADDED are removed, except one somebody has edited since - that
  edit is a decision the import did not make, so the row stays;
- rows it CHANGED go back to what they were, field by field, unless the
  field has moved again since (the changelog's own rule);
- rows it only matched were never touched.

The batch is marked ``rolled_back`` and lets go of its file hash, so the
same file can be imported again. What its balances said (#622) stands: a
bank's balance on a date is a fact the ledger is still checked against.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import queries
from app.services.finance.constants import FILE_SOURCES
from app.services.finance.domains.ledger import changelog
from app.services.finance.domains.ledger.transactions import soft_delete_transactions
from app.services.finance.models import FinanceImportBatch
from app.services.finance.utils import utcnow


@dataclass(frozen=True)
class ImportUndone:
    removed: int  # rows the import added, gone
    restored: int  # fields it changed, put back
    kept: int  # rows it added that someone has edited since


def can_undo(batch: FinanceImportBatch | None) -> bool:
    """A committed file import that added or changed something: a sync
    would come straight back, an investment ledger's trades are not rows
    this takes back, and a file that brought nothing has nothing to undo.
    The one rule the done screen, the run dialog and the routes all ask."""
    if batch is None:
        return False
    detail = batch.detail or {}
    return (
        batch.status == "committed"
        and batch.source_type in FILE_SOURCES
        and bool(batch.rows_inserted or batch.rows_updated)
        and not (detail.get("trades") or detail.get("holdings"))
    )


async def undo_import(
    db: AsyncSession, batch: FinanceImportBatch, *, owner_user_id: int | None
) -> ImportUndone:
    if not can_undo(batch) or batch.id is None:
        raise ValueError(f"Import {batch.id} cannot be undone.")
    ids = await queries.batch_row_ids(db, batch.id)
    kept = await queries.edited_since(
        db, batch.id, batch.started_at, changelog.NOT_UNDOABLE
    )
    # ponytail: an import from before #621 kept no action id, so only what
    # it added can be taken back; the restamped import_hash is not put
    # back either, so the file that made an edit re-imports as a duplicate.
    action = (batch.detail or {}).get(changelog.CHANGE_BATCH)
    restored = 0
    if ids["updated"] and action:
        restored, _ = await changelog.step_back(db, action, only=ids["updated"])
    # Removed by an undo, not by you: forget each row's identity so the
    # planner does not read it as a standing "no" and the file can come
    # back in full. One statement, before the soft-delete loads the rows.
    await queries.forget_identity(db, batch.id, keep=kept)
    with changelog.acting(changelog.UNDO):
        removed = await soft_delete_transactions(
            db, sorted(ids["inserted"] - kept), owner_user_id=owner_user_id
        )
    batch.status = "rolled_back"
    batch.file_sha256 = None
    batch.updated_at = utcnow()
    db.add(batch)
    await db.flush()
    return ImportUndone(removed=removed, restored=restored, kept=len(kept))
