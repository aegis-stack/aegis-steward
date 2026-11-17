"""The face each approval card wears (``changes.face_provider``): the mark
the register gives its subject (a payee's logo, its category's glyph, its
initial), or a paper's file badge. Batched for a queue of cards, never one
lookup per card."""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.formatting import payee_label
from app.services.change_queue import PendingChange
from app.services.finance.service import FinanceService, hydrate_streams


async def change_marks(
    db: AsyncSession, rows: list[PendingChange]
) -> dict[int, dict[str, str | None]]:
    """The brand each proposal wears (``avatar``'s arguments), by change id.

    A proposal is about a transaction, so it takes that row's mark — the
    same one the register gives it. Most payments a proposal concerns
    have no payee of their own, though, because that is usually why they
    are unmatched; when the change also names a bill, the row borrows the
    bill's brand instead of showing an initial taken off a raw bank
    descriptor. The proposal is asserting the two are the same thing.

    Both hydrations are batched. Icons are one lookup per batch and never
    per row, so neither can be folded into a loop over changes.
    """
    from app.components.backend.api.finance.register import hydrate_transactions

    service = FinanceService(db)

    def _key(row: PendingChange, name: str) -> int | None:
        value = (row.payload or {}).get(name)
        return value if isinstance(value, int) else None

    txn_ids = {i for i in (_key(r, "transaction_id") for r in rows) if i}
    stream_ids = {i for i in (_key(r, "stream_id") for r in rows) if i}

    by_txn: dict[int, dict[str, str | None]] = {}
    curated: set[int] = set()
    if txn_ids:
        found = await service.transactions_by_ids(list(txn_ids))
        for item in await hydrate_transactions(service, list(found.values())):
            if item.id is None:
                continue
            by_txn[item.id] = {
                "name": payee_label(item.merchant, item.merchant_name, item.name),
                "icon_url": item.icon_url,
                "category": item.category,
            }
            if item.merchant:
                curated.add(item.id)

    by_stream: dict[int, dict[str, str | None]] = {}
    if stream_ids:
        streams = [
            s for s in await service.streams_by_ids(list(stream_ids)) if s is not None
        ]
        for item in await hydrate_streams(service, streams, None):
            if item.id is not None:
                by_stream[item.id] = {
                    "name": item.name,
                    "icon_url": item.icon_url,
                    "category": item.category_name,
                }

    # Paper wears its file's mark. A card about a document showed the
    # first letter of its filename - "2026-08-17.pdf" came out a grey
    # "2", which is not a mark, it is the absence of one where every
    # neighbour has one (2026-09-19).
    by_document = await document_marks(
        service.db, [_key(row, "document_id") for row in rows]
    )

    marks: dict[int, dict[str, str | None]] = {}
    for row in rows:
        if row.id is None:
            continue
        if paper := by_document.get(_key(row, "document_id") or -1):
            marks[row.id] = paper
            continue
        txn_id, stream_id = _key(row, "transaction_id"), _key(row, "stream_id")
        own = by_txn.get(txn_id) if txn_id else None
        borrowed = by_stream.get(stream_id) if stream_id else None
        # The payment's own payee wins when it has one; otherwise the bill's.
        mark = own if txn_id in curated else (borrowed or own)
        if mark:
            marks[row.id] = mark
    return marks


async def document_marks(
    db: AsyncSession, document_ids: list[int | None]
) -> dict[int, dict[str, str | None]]:
    """``{document_id: mark}`` - the face a card about paper wears.

    The file's own type mark, which the shelf already draws beside every
    row of its table: one home for "what this kind of file looks like",
    and a format nobody knows gets the plain sheet rather than a guess.

    One query for the queue, never one per card.
    """
    from app.components.web_frontend.glyphs import file_badge
    from app.services.documents.service import DocumentService

    wanted = [one for one in document_ids if one]
    if not wanted:
        return {}
    return {
        document_id: {
            "name": document.title,
            "icon_url": file_badge(document.media_type, document.title)["icon"],
            "category": None,
        }
        for document_id, document in (
            await DocumentService(db).get_many(wanted)
        ).items()
    }
