"""An order email becomes a split proposal on its charge (#329).

A receipt or order email that comes in through mail is read into items
and totals by the model, kept on the document, and proposed as the
same ``transaction.split`` card chat makes - on the charge when it is
on file, or once the receipt's wait for its charge (#330) ends in an
approved match. Senders are recognized by address, as letters are.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.domains.reading import orders, receipts
from app.services.documents.models import DocumentPage
from app.services.documents.service import DocumentService
from app.services.finance.constants import transaction_tag
from app.services.finance.domains.writes.queue import approve
from tests._session import opens
from tests.services._finance_factories import (
    pending_cards,
    seed_category,
)
from tests.services._finance_factories import (
    seed_charge as _charge,
)

ORDERED = date(2026, 9, 3)
AMAZON = """From: Amazon.com <auto-confirm@amazon.com>
Subject: Your Amazon.com order #112-7
Date: 2026-09-03

Order Confirmation
Arriving Thursday
Ancient Nutrition Collagen Peptides, 16 oz   $29.99
Composition Notebooks, 4 pack                 $12.49
Item Subtotal: $42.48
Shipping: $0.00
Estimated tax: $3.64
Order Total: $46.12
"""


def _read(reading: orders.OrderReading) -> Any:
    calls: list[str] = []

    async def read(text: str, categories: list[str]) -> orders.OrderReading:
        calls.append(text)
        return reading

    read.calls = calls  # type: ignore[attr-defined]
    return read


def _reading(**over: Any) -> orders.OrderReading:
    fields: dict[str, Any] = {
        "merchant": "Amazon.com",
        "ordered_on": ORDERED,
        "total_cents": 4612,
        "items": [
            {"label": "Collagen Peptides", "amount_cents": 2999, "category": "Health"},
            {"label": "Notebooks", "amount_cents": 1249, "category": "School"},
        ],
    }
    return orders.OrderReading(**(fields | over))


async def _letter(db: AsyncSession, text: str = AMAZON) -> int:
    """A mailed message on the shelf as ``mail.ingest`` writes it."""
    document, _ = await DocumentService(db).store(
        text.encode(),
        title="Your Amazon.com order #112-7",
        kind="letter",
        media_type="text/plain",
        document_date=ORDERED,
        source="mail",
        channel="email",
        page_count=1,
    )
    db.add(
        DocumentPage(
            document_id=int(document.id or 0),
            page_number=1,
            status="read",
            method="mail",
            text=text,
        )
    )
    await db.flush()
    return int(document.id or 0)


async def _categories(db: AsyncSession) -> dict[str, int]:
    return {
        name: int((await seed_category(db, name)).id or 0)
        for name in ("Health", "School")
    }


async def _cards(db: AsyncSession, change_type: str) -> list[Any]:
    return await pending_cards(db, change_type)


class TestTheOrderIsRead:
    @pytest.mark.asyncio
    @pytest.mark.queryspy(threshold=4)  # read, matched, approved, split
    async def test_an_order_email_waits_for_its_charge_then_splits_it(
        self, async_db_session: AsyncSession
    ) -> None:
        db = async_db_session
        wanted = await _categories(db)
        document_id = await _letter(db)
        read = _read(_reading())

        await orders.propose_order(opens(db), document_id, read=read)

        # Read once and kept on the document; what it IS stays the
        # metadata card's call. Approving that names it a receipt, and
        # from there it waits for its charge.
        document = await DocumentService(db).get(document_id)
        assert document is not None and document.kind == "letter"
        assert [i["label"] for i in document.meta_data[orders.ORDER]["items"]] == [
            "Collagen Peptides",
            "Notebooks",
        ]
        assert len(read.calls) == 1
        await DocumentService(db).update(document_id, {"kind": "receipt"})
        assert await _cards(db, receipts.RECEIPT) == []

        # The charge posts; the match is proposed, approving it files the
        # receipt and proposes the split chat would have made.
        charge = await _charge(db, -4612, ORDERED + timedelta(days=2), "AMAZON MKTPL")
        assert await receipts.match_waiting(db, owner_user_id=None) == 1
        (match,) = await _cards(db, receipts.RECEIPT)
        await approve(db, int(match.id or 0))

        (split,) = await _cards(db, "transaction.split")
        assert split.payload["transaction_id"] == charge
        assert split.payload["parts"] == [
            {
                "amount": 2999,
                "category_id": wanted["Health"],
                "memo": "Collagen Peptides",
            },
            {"amount": 1249, "category_id": wanted["School"], "memo": "Notebooks"},
        ]
        assert split.proposed_by_agent == "reading"

    @pytest.mark.asyncio
    @pytest.mark.queryspy(threshold=3)  # read once, asked to read again
    async def test_a_receipt_already_on_its_charge_is_split_at_once_and_read_once(
        self, async_db_session: AsyncSession
    ) -> None:
        db = async_db_session
        await _categories(db)
        document_id = await _letter(db)
        charge = await _charge(db, -4612, ORDERED, "AMAZON MKTPL")
        await DocumentService(db).tag(document_id, transaction_tag(charge))
        read = _read(_reading())

        await orders.propose_order(opens(db), document_id, read=read)
        await orders.propose_order(opens(db), document_id, read=read)

        (split,) = await _cards(db, "transaction.split")
        assert split.payload["transaction_id"] == charge
        assert len(read.calls) == 1

    @pytest.mark.asyncio
    async def test_mail_that_is_not_an_order_is_not_read(
        self, async_db_session: AsyncSession
    ) -> None:
        db = async_db_session
        document_id = await _letter(
            db,
            "From: Delta Dental <claims@deltadentalins.com>\nSubject: Your claim\n\n"
            "Your claim was processed. See the attached statement.\n",
        )
        read = _read(_reading())

        await orders.propose_order(opens(db), document_id, read=read)

        assert read.calls == []
        document = await DocumentService(db).get(document_id)
        assert document is not None and document.kind == "letter"


class TestWhatIsBelieved:
    def test_an_order_is_known_by_its_words_and_a_total(self) -> None:
        assert orders.looks_like_order([{"page": 1, "text": AMAZON}])
        assert not orders.looks_like_order(
            [{"page": 1, "text": "From: Delta Dental\n\nYour claim was processed.\n"}]
        )
        # Money without the words is a statement, not an order.
        assert not orders.looks_like_order(
            [{"page": 1, "text": "Statement\nNew balance: $46.12\nTotal due $46.12\n"}]
        )

    def test_items_the_page_does_not_print_are_dropped(self) -> None:
        reading = _reading(
            items=[
                {
                    "label": "Collagen Peptides",
                    "amount_cents": 2999,
                    "category": "Health",
                },
                {"label": "Invented", "amount_cents": 999, "category": "Health"},
            ]
        )
        kept = orders.checked(reading, [{"page": 1, "text": AMAZON}])
        assert [i.label for i in kept.items] == ["Collagen Peptides"]

    def test_parts_never_exceed_the_charge_and_share_a_promotion(self) -> None:
        """Listed prices above the charge: the difference is a promotion
        spread across the items in proportion, as the chat rule says."""
        kept = orders.checked(
            _reading(
                items=[
                    {"label": "A", "amount_cents": 3000, "category": "Health"},
                    {"label": "B", "amount_cents": 3000, "category": "School"},
                ],
            ),
            [{"page": 1, "text": "Order\nA $30.00\nB $30.00\nOrder Total: $54.12\n"}],
        )
        parts = orders.parts_for(
            kept, charge_cents=5412, categories={"Health": 1, "School": 2}
        )
        assert [(p["amount"], p["category_id"]) for p in parts] == [
            (2706, 1),
            (2706, 2),
        ]

    def test_an_item_in_no_known_category_stays_in_the_remainder(self) -> None:
        kept = orders.checked(
            _reading(items=[{"label": "A", "amount_cents": 3000, "category": "Toys"}]),
            [{"page": 1, "text": "Order\nA $30.00\nOrder Total: $30.00\n"}],
        )
        assert orders.parts_for(kept, charge_cents=3000, categories={"Health": 1}) == []
