"""The mail service's reads that are not the ingest's own: the mailbox
rows a pull keeps its place in."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.mail.models import MailMailbox


async def mailbox_state(db: AsyncSession, key: str) -> MailMailbox | None:
    """Where the pull of a mailbox got to, or nothing if never tried."""
    return (await db.exec(select(MailMailbox).where(MailMailbox.key == key))).first()


async def mailbox(db: AsyncSession, key: str) -> MailMailbox:
    """The row for a mailbox, made on first sight."""
    found = await mailbox_state(db, key)
    if found is None:
        found = MailMailbox(key=key)
        db.add(found)
        await db.flush()
    return found


async def mark_pulled(
    db: AsyncSession, mailbox_id: int, *, uidvalidity: int, uid_last: int
) -> None:
    """A pull that worked: the watermark it reached, and no error."""
    row = await db.get(MailMailbox, mailbox_id)
    assert row is not None
    row.uidvalidity, row.uid_last = uidvalidity, uid_last
    row.last_pulled_at, row.last_error = utcnow(), None
    db.add(row)
    await db.flush()


async def mark_failed(db: AsyncSession, mailbox_id: int, error: str) -> None:
    """A pull that did not: the one line why. The watermark stays."""
    row = await db.get(MailMailbox, mailbox_id)
    assert row is not None
    row.last_error = error
    db.add(row)
    await db.flush()
