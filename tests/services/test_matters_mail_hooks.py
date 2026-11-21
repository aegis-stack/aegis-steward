"""Matters' mail hook: who sent each message, and what that files.

Mail files each message once and hands the batch's new rows to the hooks
registered on ``register_messages_filed``; ``app.services.matters.mail_hooks``
is matters' (found by its name). These run real imports, so the hook is
reached the way production reaches it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.models import Document
from app.services.mail import ingest
from app.services.mail.models import MailAttachment, MailMessage
from app.services.matters.service import PartyService
from tests._mbox import PDF, eml_bytes, mbox_bytes, message
from tests._session import rows_of


async def _cards(db: AsyncSession) -> list[Any]:
    from app.services.change_queue import PendingChange

    return list(
        (
            await db.exec(
                select(PendingChange).where(
                    PendingChange.change_type == "contact.create"
                )
            )
        ).all()
    )


class TestTheLetterIsRead:
    @pytest.mark.asyncio
    async def test_the_body_becomes_a_letter_already_read(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        from app.services.documents.models import DocumentPage

        sent = datetime(2026, 8, 27, 9, 5, tzinfo=UTC)
        data = eml_bytes(
            message(
                sender="Example Dental <Claims@Dental.example>",
                subject="Your claim has been processed",
                body="Your claim was paid. Call 800-555-0100 with questions.",
                sent=sent,
            )
        )
        result = await ingest.ingest_mail(
            open_session, data=data, file_name="claim.eml"
        )

        [letter] = await rows_of(async_db_session, Document)
        assert (
            letter.kind == "letter" and letter.title == "Your claim has been processed"
        )
        assert letter.source == "mail" and letter.channel == "email"
        assert letter.document_date == sent.date()
        [page] = await rows_of(async_db_session, DocumentPage)
        # Already read: the mail IS text. Extraction skips a read page and
        # goes straight to proposing, so the letter says who it is from
        # the same way a scanned one does.
        assert page.document_id == letter.id and page.status == "read"
        assert page.method == "mail"
        lines = (page.text or "").splitlines()
        # The header is the letterhead: the address sits on page 1 for the
        # identity rules, the subject and date beside it.
        assert lines[0] == "From: Example Dental <claims@dental.example>"
        assert "Your claim was paid." in page.text
        [row] = await rows_of(async_db_session, MailMessage)
        assert row.document_id == letter.id
        assert result.letters_filed == 1
        assert dispatched == [letter.id]


class TestTheSenderIsKnown:
    @pytest.mark.asyncio
    async def test_an_address_on_file_names_the_contact(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        dental = await PartyService(async_db_session).create(
            name="Example Dental",
            kind="organization",
            contact={"email": "Claims@Dental.example"},
        )
        data = eml_bytes(message(sender="Example Dental <claims@dental.example>"))
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")

        [row] = await rows_of(async_db_session, MailMessage)
        # Case is the sender's to choose and nobody's to match on.
        assert row.party_id == dental.id

    @pytest.mark.asyncio
    async def test_a_labelled_reach_line_is_an_address_too(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        """A county office prints its caseworker's address as readily as
        its main one; ``also`` lines carry those, and they count."""
        county = await PartyService(async_db_session).create(
            name="Example County DSS",
            kind="organization",
            contact={"also": [{"label": "caseworker", "value": "jdoe@example.gov"}]},
        )
        data = eml_bytes(message(sender="J Doe <JDOE@example.gov>"))
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")

        [row] = await rows_of(async_db_session, MailMessage)
        assert row.party_id == county.id

    @pytest.mark.queryspy(allow_n_plus_one=True)
    @pytest.mark.asyncio
    async def test_a_domain_on_file_claims_every_address_at_it(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        """A school writes through a platform from one address per teacher,
        and a new teacher is a new address. ``@domain`` on a contact claims
        them all, and nobody is offered as a stranger."""
        school = await PartyService(async_db_session).create(
            name="Example School",
            kind="organization",
            contact={"also": [{"label": "mail from", "value": "@School.example"}]},
        )
        for n, who in enumerate(("Ms A", "Mr B")):
            data = eml_bytes(
                message(
                    sender=f"{who} via School <donotreply+{n}@school.example>",
                    message_id=f"<t{n}@school.example>",
                )
            )
            await ingest.ingest_mail(open_session, data=data, file_name=f"{n}.eml")

        rows = await rows_of(async_db_session, MailMessage)
        assert [row.party_id for row in rows] == [school.id, school.id]
        assert await _cards(async_db_session) == []

    @pytest.mark.asyncio
    async def test_an_exact_address_beats_a_domain_claim(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        parties = PartyService(async_db_session)
        await parties.create(
            name="Example School",
            kind="organization",
            contact={"also": [{"label": "mail from", "value": "@school.example"}]},
        )
        nurse = await parties.create(
            name="School Nurse",
            kind="person",
            contact={"email": "nurse@school.example"},
        )
        data = eml_bytes(message(sender="Nurse <nurse@school.example>"))
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")

        [row] = await rows_of(async_db_session, MailMessage)
        assert row.party_id == nurse.id

    @pytest.mark.asyncio
    async def test_a_stranger_is_kept_and_named_nobody(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        data = eml_bytes(message(sender="Someone <who@nowhere.example>"))
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")
        [row] = await rows_of(async_db_session, MailMessage)
        assert row.party_id is None and row.from_address == "who@nowhere.example"


class TestAStrangerIsOfferedAsAContact:
    """The letterhead rule refuses to GUESS a sender off a printed line -
    that is how a second address book starts. A From header is not a
    guess: the sender asserted a name and an address. So a stranger is
    offered as a card (contact.create) and never written - ST-08's rule -
    and approving it files the letter under them on the next read."""

    @pytest.mark.asyncio
    async def test_an_unknown_sender_becomes_a_card(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        data = eml_bytes(
            message(
                sender="Provider Financial <OF-Service@of.provider.example>",
                subject="Your HSA Statement is Now Available",
            )
        )
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")

        [card] = await _cards(async_db_session)
        assert card.status == "pending" and card.proposed_by_agent == "mail"
        assert card.payload["name"] == "Provider Financial"
        assert card.payload["kind"] == "organization"
        assert card.payload["email"] == "of-service@of.provider.example"
        assert "Your HSA Statement is Now Available" in card.payload["note"]

    @pytest.mark.asyncio
    async def test_a_sender_on_file_is_a_match_not_a_stranger(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        await PartyService(async_db_session).create(
            name="Example Dental",
            kind="organization",
            contact={"email": "claims@dental.example"},
        )
        data = eml_bytes(message(sender="Example Dental <claims@dental.example>"))
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")
        assert await _cards(async_db_session) == []

    @pytest.mark.asyncio
    async def test_one_card_per_stranger_however_often_they_wrote(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        twice = [
            message(sender="Someone <who@nowhere.example>", subject="first"),
            message(sender="Someone <who@nowhere.example>", subject="second"),
        ]
        await ingest.ingest_mail(
            open_session, data=mbox_bytes(twice), file_name="x.mbox"
        )
        assert len(await _cards(async_db_session)) == 1

    @pytest.mark.queryspy(allow_n_plus_one=True)
    @pytest.mark.asyncio
    async def test_a_card_already_waiting_is_not_offered_again(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        """Two exports, weeks apart, same unknown sender, nobody has
        answered the first card yet."""
        first = eml_bytes(message(sender="Someone <who@nowhere.example>", subject="a"))
        await ingest.ingest_mail(open_session, data=first, file_name="a.eml")
        second = eml_bytes(message(sender="Someone <who@nowhere.example>", subject="b"))
        await ingest.ingest_mail(open_session, data=second, file_name="b.eml")
        assert len(await _cards(async_db_session)) == 1

    @pytest.mark.queryspy(allow_n_plus_one=True)
    @pytest.mark.asyncio
    async def test_a_rejected_card_is_not_offered_again(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        """No means no. A sender whose card was rejected writes again
        next month; offering them again is asking a question that was
        answered."""
        first = eml_bytes(message(sender="Someone <who@nowhere.example>", subject="a"))
        await ingest.ingest_mail(open_session, data=first, file_name="a.eml")
        [card] = await _cards(async_db_session)
        card.status = "rejected"
        async_db_session.add(card)
        await async_db_session.commit()

        second = eml_bytes(message(sender="Someone <who@nowhere.example>", subject="b"))
        await ingest.ingest_mail(open_session, data=second, file_name="b.eml")
        assert len(await _cards(async_db_session)) == 1

    @pytest.mark.asyncio
    async def test_a_card_somebody_else_proposed_counts_too(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        """The letterhead reader proposed this address off a PDF and the
        card is still waiting. Mail offering a second one is asking the
        same question twice - it does not matter who asked first."""
        from app.services.change_queue import propose

        await propose(
            async_db_session,
            "contact.create",
            {
                "name": "Provider Financial",
                "kind": "organization",
                "email": "of-service@of.provider.example",
            },
            proposed_by_agent="steward",
            owner_user_id=None,
        )
        data = eml_bytes(message(sender="of-service@of.provider.example"))
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")

        assert len(await _cards(async_db_session)) == 1

    @pytest.mark.asyncio
    async def test_no_display_name_means_the_domain_is_the_name(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        """``From: of-service@of.provider.example`` - no name at all. The address
        is not a name anybody would file under; the domain's own label is
        the nearest thing to one, and the address stays on the card."""
        data = eml_bytes(message(sender="of-service@of.provider.example"))
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")
        [card] = await _cards(async_db_session)
        assert card.payload["name"] == "Provider"
        assert card.payload["email"] == "of-service@of.provider.example"


class TestPaperIsFiledUnderTheSender:
    """Matching the address names the sender; the paper should then sit
    with them, the way a letter approved off a letterhead does - the
    same party tag, so Contacts shows it and nothing else has to learn
    a second way of filing. A stranger's paper waits for the card, and
    approving the card adopts everything they already sent."""

    @pytest.mark.asyncio
    async def test_a_known_senders_letter_and_attachments_are_filed_under_them(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        from app.services.documents.service import DocumentService
        from app.services.matters.models.core import party_tag

        dental = await PartyService(async_db_session).create(
            name="Example Dental",
            kind="organization",
            contact={"email": "claims@dental.example"},
        )
        data = eml_bytes(
            message(
                sender="Example Dental <claims@dental.example>",
                attachments=[("statement.pdf", "application/pdf", PDF)],
            )
        )
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")

        docs = DocumentService(async_db_session)
        [row] = await rows_of(async_db_session, MailMessage)
        [link] = await rows_of(async_db_session, MailAttachment)
        assert await docs.tags_for(int(row.document_id)) == [party_tag(int(dental.id))]
        assert await docs.tags_for(link.document_id) == [party_tag(int(dental.id))]

    @pytest.mark.queryspy(allow_n_plus_one=True)
    @pytest.mark.asyncio
    async def test_approving_a_strangers_card_adopts_what_they_sent(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        from app.services.change_queue import approve
        from app.services.documents.service import DocumentService
        from app.services.matters.models.core import party_tag

        data = eml_bytes(
            message(
                sender="Provider Financial <of-service@of.provider.example>",
                attachments=[("statement.pdf", "application/pdf", PDF)],
            )
        )
        await ingest.ingest_mail(open_session, data=data, file_name="x.eml")
        [row] = await rows_of(async_db_session, MailMessage)
        assert row.party_id is None
        [card] = await _cards(async_db_session)

        done = await approve(async_db_session, int(card.id), owner_user_id=None)
        party_id = int(done.result["party_id"])

        await async_db_session.refresh(row)
        assert row.party_id == party_id
        docs = DocumentService(async_db_session)
        [link] = await rows_of(async_db_session, MailAttachment)
        assert await docs.tags_for(int(row.document_id)) == [party_tag(party_id)]
        assert await docs.tags_for(link.document_id) == [party_tag(party_id)]

    @pytest.mark.queryspy(allow_n_plus_one=True)
    @pytest.mark.asyncio
    async def test_a_domain_added_to_a_contact_adopts_what_it_already_sent(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        """The edit on the Contacts page is the way in: mail already on the
        shelf from the domain is the contact's from then on."""
        from app.services.documents.service import DocumentService
        from app.services.matters.models.core import party_tag

        for n in range(2):
            data = eml_bytes(
                message(
                    sender=f"Teacher {n} <donotreply+{n}@school.example>",
                    message_id=f"<t{n}@school.example>",
                )
            )
            await ingest.ingest_mail(open_session, data=data, file_name=f"{n}.eml")
        parties = PartyService(async_db_session)
        school = await parties.create(name="Example School", kind="organization")

        await parties.update(
            int(school.id),
            {"contact": {"also": [{"label": "mail from", "value": "@school.example"}]}},
        )

        rows = await rows_of(async_db_session, MailMessage)
        assert [row.party_id for row in rows] == [school.id, school.id]
        docs = DocumentService(async_db_session)
        for row in rows:
            assert await docs.tags_for(int(row.document_id)) == [
                party_tag(int(school.id))
            ]

    @pytest.mark.queryspy(allow_n_plus_one=True)
    @pytest.mark.asyncio
    async def test_a_domain_claims_only_addresses_at_it(
        self, async_db_session: AsyncSession, open_session: Any, dispatched: list[int]
    ) -> None:
        """The suffix starts at the "@", and what is typed is matched as
        characters: ``_`` is not a wildcard."""
        for n, address in enumerate(("a@notschool.example", "b@schoolxexample")):
            data = eml_bytes(message(sender=address, message_id=f"<o{n}@x.example>"))
            await ingest.ingest_mail(open_session, data=data, file_name=f"{n}.eml")
        parties = PartyService(async_db_session)
        school = await parties.create(name="Example School", kind="organization")

        for claim in ("@school_example", "@school.example"):
            await parties.update(
                int(school.id),
                {"contact": {"also": [{"label": "mail from", "value": claim}]}},
            )

        rows = await rows_of(async_db_session, MailMessage)
        assert [row.party_id for row in rows] == [None, None]


def test_the_mail_models_alone_resolve_every_link() -> None:
    """The worker's pull loads mail's ingest and what it imports, nothing
    of matters. ``party_id`` points at matters' table, so mail's models
    must bring it: without it the first flush raised
    NoReferencedTableError and every pull failed."""
    import subprocess
    import sys

    code = (
        "import app.services.mail.ingest\n"
        "import app.services.mail.models as m\n"
        "for fk in m.MailMessage.__table__.foreign_keys: fk.column\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-600:]
