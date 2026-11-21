"""Matters' reads: the contacts mail's senders are matched against, and
the cards that offered to add one."""

from __future__ import annotations

from sqlmodel import col, or_, select
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


async def unadopted_mail_from(
    db: AsyncSession, addresses: list[str]
) -> list[MailMessage]:
    """What these addresses sent that no contact holds yet; an ``@domain``
    is every address at it. One query for the lot."""
    exact = [a for a in addresses if not a.startswith("@")]
    # A suffix match that starts at the "@", so ``x@notschool.example``
    # is not the school's; escaped, so a "%" or "_" typed in the domain is
    # a character, never a wildcard.
    domains = [
        col(MailMessage.from_address).endswith(a, autoescape=True)
        for a in addresses
        if a.startswith("@")
    ]
    rows = await db.exec(
        select(MailMessage).where(
            or_(col(MailMessage.from_address).in_(exact), *domains),
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
