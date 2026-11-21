"""Mail's senders, matched to contacts: matters' hook on the mail service.

Mail files each message once and hands the batch's new rows to whatever
registered with ``register_messages_filed``; ingest finds this module by
its name. Who a sender IS is a contacts question, so it is answered here:

- A sender whose address is a contact's has their letter and attachments
  filed under them (the party tag an approved letterhead filing writes,
  so Contacts shows it and nothing learns a second way of filing).
- A stranger is offered as a ``contact.create`` card, never added: once
  per address, and a rejected one is never asked again (no means no).
- An approved card adopts what that address already sent (``adopt_sender``).
- Each letter is read as a scan is (``read_the_letters``): the template
  files it already read and stops; here the reading names, dates and
  files it, and a mailed receipt is matched off its From line.

The Mail page and the ``arrivals`` tool say which, through ``senders_of``
and ``told``.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.change_queue import propose
from app.services.documents.domains.extraction.dispatch import read_quietly
from app.services.documents.domains.reading.identity import parties_by_email
from app.services.documents.service import DocumentService
from app.services.mail import queries as mail_queries
from app.services.mail.arrivals import Arrival
from app.services.mail.ingest import register_messages_filed
from app.services.mail.models import MailMessage
from app.services.matters import queries
from app.services.matters.models.core import party_tag


async def file_under_senders(
    db: AsyncSession, rows: list[MailMessage], owner_user_id: int | None
) -> None:
    """A batch's new messages: each known sender's paper filed under them,
    each stranger offered as a card."""
    senders = await parties_by_email(db)
    offered = await _strangers_already_offered(db)
    papers = await _papers_of(db, rows)
    documents = DocumentService(db)
    for row in rows:
        party_id = senders.get(row.from_address)
        if party_id is not None:
            row.party_id = party_id
            db.add(row)
            for document_id in papers.get(int(row.id or 0), []):
                await documents.tag(document_id, party_tag(party_id))
        elif row.from_address:
            await _offer_contact(db, row, offered=offered, owner_user_id=owner_user_id)
    await db.flush()


async def read_the_letters(
    db: AsyncSession, rows: list[MailMessage], owner_user_id: int | None
) -> None:
    """Each new message's letter, sent to be read like any paper. Never
    forced: a letter already on file is not read again."""
    for row in rows:
        if row.document_id is not None:
            await read_quietly(row.document_id, owner_user_id=owner_user_id)


# Senders first, so a letter is under its contact before it is read.
register_messages_filed(file_under_senders)
register_messages_filed(read_the_letters)


async def adopt_sender(db: AsyncSession, party_id: int, address: str | None) -> int:
    """A stranger's card was approved: everything they already sent is
    theirs now - the message rows name them, and their letters and
    attachments are filed under them the way a known sender's are on
    ingest. Returns how many messages were adopted."""
    if not address:
        return 0
    rows = await queries.unadopted_mail_from(db, address)
    papers = await _papers_of(db, rows)
    documents = DocumentService(db)
    for row in rows:
        row.party_id = party_id
        db.add(row)
        for document_id in papers.get(int(row.id or 0), []):
            await documents.tag(document_id, party_tag(party_id))
    await db.flush()
    return len(rows)


async def senders_of(
    db: AsyncSession, rows: list[MailMessage]
) -> tuple[dict[int, str], dict[str, str]]:
    """For the Mail page: the contact names these messages were filed
    under, and each address's card status. Two queries, not one a row."""
    party_ids = {row.party_id for row in rows if row.party_id is not None}
    names = await queries.party_names(db, party_ids)
    return names, await cards_by_address(db)


def told(
    arrival: Arrival, row: MailMessage, names: dict[int, str], cards: dict[str, str]
) -> Arrival:
    """An arrival as Steward says it: who it was filed under, or what the
    card offering its sender is waiting on."""
    party = (
        {"id": row.party_id, "name": names.get(row.party_id, "")}
        if row.party_id is not None
        else None
    )
    card = cards.get(row.from_address)
    became = arrival.became
    if not became.startswith("nothing"):
        if party is not None:
            became = f"{became}, filed under {party['name']}"
        elif card == "pending":
            became = f"{became}; a card offers to add {arrival.sender}"
        elif card == "rejected":
            became = f"{became}; {arrival.sender} was declined as a contact"
    return arrival.model_copy(update={"party": party, "card": card, "became": became})


async def cards_by_address(db: AsyncSession) -> dict[str, str]:
    """The status of the contact.create card offering each address, by
    the latest card for it.

    One home, because two questions are the same question: ingest asks
    "have we already offered this stranger?" and the Mail page asks
    "what happened to the card for this message?". Not filtered by who
    proposed it - a card the letterhead reader raised off a PDF is
    still an unanswered question about this address, and asking it
    again from mail is asking twice.
    """
    rows = await queries.contact_cards(db)
    return {
        str(row.payload["email"]).lower(): row.status
        for row in rows
        if row.payload.get("email")
    }


async def _strangers_already_offered(db: AsyncSession) -> set[str]:
    """Addresses nobody needs asked about again: a card is waiting, or a
    rejected one already answered - no means no."""
    return {
        address
        for address, status in (await cards_by_address(db)).items()
        if status in ("pending", "rejected")
    }


async def _papers_of(db: AsyncSession, rows: list[MailMessage]) -> dict[int, list[int]]:
    """Each message's letter and attachments, by message id, in one query."""
    ids = [int(row.id or 0) for row in rows]
    found: dict[int, list[int]] = {
        int(row.id or 0): [row.document_id] if row.document_id else [] for row in rows
    }
    for link in await mail_queries.attachments_of(db, ids):
        found[link.message_id].append(link.document_id)
    return found


def _domain_name(address: str) -> str:
    """``notices@of.example.com`` -> ``Example``: the label before the TLD,
    when the header gave no name. ponytail: a two-part public suffix
    (``bank.co.uk`` -> ``Co``) is wrong; the card is where it is fixed."""
    labels = address.rpartition("@")[2].split(".")
    return (labels[-2] if len(labels) >= 2 else labels[0]).capitalize() or address


async def _offer_contact(
    db: AsyncSession,
    row: MailMessage,
    *,
    offered: set[str],
    owner_user_id: int | None,
) -> None:
    """A stranger wrote. Offer to add them - never add them.

    The letterhead rule refuses to guess a sender off a printed line,
    because that is how a second address book starts. A From header is
    not a guess: the sender asserted a name and an address. Still a card
    (ST-08: extraction proposes, never writes), once per address.

    ``kind`` is the one guess. A header cannot tell a county caseworker
    from a claims robot, so it says organization and the card is where
    that gets corrected - not a name-shape rule, which is the kind of
    rule this codebase keeps having to take back.
    """
    address = row.from_address
    if address in offered:
        return
    offered.add(address)
    when = row.sent_at.date().isoformat() if row.sent_at else "an unknown date"
    await propose(
        db,
        "contact.create",
        {
            "name": row.from_name or _domain_name(address),
            "kind": "organization",
            "email": address,
            "note": f"Wrote on {when}: {row.subject or '(no subject)'}",
        },
        owner_user_id=owner_user_id,
        proposed_by_agent="mail",
    )
