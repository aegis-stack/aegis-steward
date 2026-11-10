"""An order email becomes a split proposal on its charge (#329).

A receipt or order email on the shelf (a mailed letter, a forwarded
confirmation, an itemized PDF) is read into its items and total by the
model, once, and the reading is kept on the document. The charge gets
the same ``transaction.split`` card chat makes: at once when the
receipt is already on it, or when its wait for the charge (#330) ends
in an approved match. The model READS; what is believed is checked
against the page, and a person approves.
"""

from __future__ import annotations

from datetime import date
from itertools import islice
import re
import textwrap
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import OpenSession
from app.core.money import plain_dollars
from app.services.documents.domains.reading.figures import MONEY
from app.services.documents.domains.reading.findings import Page, flat
from app.services.documents.domains.reading.metadata import opening_lines
from app.services.documents.domains.reading.model import (
    pages_text,
    read_with_model,
    when_reachable,
)
from app.services.documents.domains.reading.receipts import PROPOSED_BY, read_total

SURFACE = "documents:read-order"
# Where a document keeps what its order said.
ORDER = "order"
SPLIT = "transaction.split"
# The words an order or receipt opens with, on its first lines.
_ORDER_WORDS = re.compile(
    r"\b(order|receipt|invoice|your purchase|thank you for)\b", re.I
)
_OPENING_LINES = 8
_MEMO_CHARS = 120

INSTRUCTIONS = (
    "You read one order confirmation or receipt and report what was bought. "
    "Report every line item with the price printed for it, in cents, and the "
    "quantity when one is printed. Give each item the ONE category from the "
    "list offered that fits it best, or null when none does. Report the "
    "merchant, the order date and the total charged only when the page states "
    "them. Never add an item the page does not print, never total or tax an "
    "item yourself, and never summarize or advise."
)


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="The item as the page names it.")
    quantity: int = Field(default=1, ge=1, description="How many, when printed.")
    amount_cents: int = Field(
        ge=0, description="The price printed for the line, in cents."
    )
    category: str | None = Field(
        default=None, description="One of the categories offered, or null."
    )


class OrderReading(BaseModel):
    """What an order says it was, as the model reports it."""

    model_config = ConfigDict(extra="forbid")

    merchant: str | None = Field(default=None, description="Who sold it.")
    ordered_on: date | None = Field(default=None, description="The order date.")
    total_cents: int | None = Field(default=None, description="The total charged.")
    items: list[OrderItem] = Field(default=[], description="Every line item.")


def looks_like_order(pages: list[Page]) -> bool:
    """Worth a model call: it calls itself an order or a receipt on its
    opening lines, prints a total, and prices more than one thing."""
    opening = "\n".join(
        said for _page, said in islice(opening_lines(pages), _OPENING_LINES)
    )
    if not _ORDER_WORDS.search(opening) or read_total(pages) is None:
        return False
    priced = sum(len(MONEY.findall(page["text"] or "")) for page in pages)
    return priced >= 3


def checked(reading: OrderReading, pages: list[Page]) -> OrderReading:
    """The reading with only the items whose printed price the page
    carries; the rest were the model's."""
    said = flat(" ".join(page["text"] or "" for page in pages))
    kept = [
        item for item in reading.items if item.amount_cents and _printed(item, said)
    ]
    return reading.model_copy(update={"items": kept})


def _printed(item: OrderItem, said: str) -> bool:
    """The item's price is on the page as a figure of its own: "9.99" is
    not printed where "$29.99" is."""
    figure = re.escape(plain_dollars(item.amount_cents))
    return re.search(rf"(?<![\d.]){figure}(?!\d)", said) is not None


def parts_for(
    order: OrderReading, *, charge_cents: int, categories: dict[str, int]
) -> list[dict[str, Any]]:
    """The split's parts, one per category the items fall in, as the
    chat rule makes them: only what is known (an item in no known
    category stays in the remainder), and where listed prices exceed
    the charge, the promotion spread across the items in proportion so
    the parts total the charge."""
    by_category: dict[int, tuple[int, list[str]]] = {}
    for item in order.items:
        category_id = categories.get(item.category or "")
        if category_id is None:
            continue
        cents, labels = by_category.get(category_id, (0, []))
        by_category[category_id] = (cents + item.amount_cents, [*labels, item.label])
    listed = sum(cents for cents, _ in by_category.values())
    if listed > charge_cents > 0:
        scaled = {
            category_id: (round(cents * charge_cents / listed), labels)
            for category_id, (cents, labels) in by_category.items()
        }
        # Rounding lands on the largest part, so the parts total the charge.
        largest = max(scaled, key=lambda c: scaled[c][0])
        short = charge_cents - sum(cents for cents, _ in scaled.values())
        scaled[largest] = (scaled[largest][0] + short, scaled[largest][1])
        by_category = scaled
    return [
        {"amount": cents, "category_id": category_id, "memo": _memo(labels)}
        for category_id, (cents, labels) in by_category.items()
        if cents > 0
    ]


def _memo(labels: list[str]) -> str:
    return textwrap.shorten(", ".join(labels), _MEMO_CHARS, placeholder="…")


async def read_order(text: str, categories: list[str]) -> OrderReading:
    """Hand the order's text and the household's categories to the model."""
    offered = ", ".join(categories) or "(none)"
    return await read_with_model(
        f"Categories offered: {offered}.\n\nRead this order.\n\n{text}",
        instructions=INSTRUCTIONS,
        output_type=OrderReading,
        surface=SURFACE,
    )


async def order_reader():  # noqa: ANN201
    """The reader, or None when no model is reachable."""
    return await when_reachable(read_order)


async def propose_order(
    open_session: OpenSession,
    document_id: int,
    *,
    owner_user_id: int | None = None,
    read: Any | None = None,
) -> bool:
    """Read an order once and keep it on the document; then its split on
    the charge it is already on. Returns whether an order was read.

    What the paper IS (a receipt, dated when) is the metadata card's to
    propose, as for every reading; approving that starts its wait for
    the charge (#330). The reader is resolved only once the pattern
    says the page is worth a model call. The model call holds no
    session: an open session is the app's write lock (``OpenSession``)."""
    from app.services.documents.domains.reading.asked import read_pages
    from app.services.documents.service import DocumentService
    from app.services.finance.service import list_categories

    async with open_session() as db:
        document = await DocumentService(db).get(document_id)
        if document is None or ORDER in document.meta_data:
            return False
        pages = await read_pages(db, document_id)
        if not looks_like_order(pages):
            return False
        categories = {
            c.name: int(c.id or 0)
            for c in await list_categories(db, owner_user_id=owner_user_id)
        }
    read = read or await order_reader()
    if read is None:
        return False
    order = checked(await read(pages_text(pages), list(categories)), pages)
    async with open_session() as db:
        document = await DocumentService(db).get(document_id)
        if document is None:
            return False
        document.meta_data = {
            **document.meta_data,
            ORDER: order.model_dump(mode="json"),
        }
        db.add(document)
        await db.flush()
        charge = await _charge_of(db, document_id)
        if charge is not None:
            await propose_split(
                db,
                document_id,
                charge,
                owner_user_id=owner_user_id,
                categories=categories,
            )
        await db.commit()
    return True


async def _charge_of(db: AsyncSession, document_id: int) -> int | None:
    """The transaction this receipt is filed on, if it is on one."""
    from app.services.documents.service import DocumentService
    from app.services.finance.constants import tagged_transaction

    for label in await DocumentService(db).tags_for(document_id):
        if (transaction_id := tagged_transaction(label)) is not None:
            return transaction_id
    return None


async def propose_split(
    db: AsyncSession,
    document_id: int,
    transaction_id: int,
    *,
    owner_user_id: int | None,
    categories: dict[str, int] | None = None,
) -> bool:
    """The order kept on this document as a split card on its charge,
    once; nothing when no order was read, no item fell in a category
    the household has, or the charge already has a card. A caller that
    has the household's categories by name hands them over."""
    from app.services.documents.domains.reading.asked import already_asked
    from app.services.documents.service import DocumentService
    from app.services.finance.service import (
        FinanceTransaction,
        list_categories,
        propose,
    )

    document = await DocumentService(db).get(document_id)
    kept = (document.meta_data if document else {}).get(ORDER)
    if not kept or await already_asked(db, SPLIT, transaction_id, key="transaction_id"):
        return False
    charge = await db.get(FinanceTransaction, transaction_id)
    if charge is None:
        return False
    order = OrderReading.model_validate(kept)
    if categories is None:
        categories = {
            c.name: int(c.id or 0)
            for c in await list_categories(db, owner_user_id=owner_user_id)
        }
    parts = parts_for(order, charge_cents=abs(charge.amount), categories=categories)
    if not parts:
        return False
    await propose(
        db,
        SPLIT,
        {"transaction_id": transaction_id, "parts": parts},
        owner_user_id=owner_user_id,
        proposed_by_agent=PROPOSED_BY,
    )
    return True
