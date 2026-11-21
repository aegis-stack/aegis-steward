"""Matters' reads: the contacts mail's senders are matched against, and
the cards that offered to add one."""

from __future__ import annotations

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.change_queue import PendingChange
from app.services.mail.models import MailMessage
from app.services.matters.models.core import Party


async def party_names(db: AsyncSession, party_ids: set[int]) -> dict[int, str]:
    """Each contact's name, by id, in one query."""
    if not party_ids:
        return {}
    rows = await db.exec(select(Party).where(col(Party.id).in_(party_ids)))
    return {int(p.id or 0): p.name for p in rows.all()}


async def unadopted_mail_from(db: AsyncSession, address: str) -> list[MailMessage]:
    """What this address sent that no contact holds yet."""
    rows = await db.exec(
        select(MailMessage).where(
            MailMessage.from_address == address.lower(),
            col(MailMessage.party_id).is_(None),
        )
    )
    return list(rows.all())


async def contact_cards(db: AsyncSession) -> list[PendingChange]:
    """Every card offering to add a contact, oldest first."""
    rows = await db.exec(
        select(PendingChange)
        .where(PendingChange.change_type == "contact.create")
        .order_by(col(PendingChange.id))
    )
    return list(rows.all())
