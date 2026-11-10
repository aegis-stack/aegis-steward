"""Two reads every proposer makes: the pages as a reader takes them,
and whether a card for this paper is already waiting."""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.domains.reading.findings import Page


async def already_asked(
    db: AsyncSession, change_type: str, document_id: int, *, key: str = "document_id"
) -> bool:
    """A pending card for this document is the answer already waiting.
    Reading again must not stack a second one on top of it. ``key`` is
    the payload field that names the thing asked about, for a card that
    is about an account rather than the paper."""
    from app.services.finance.service import list_changes

    return any(
        change.payload.get(key) == document_id
        for change in await list_changes(db, status="pending")
        if change.change_type == change_type
    )


async def read_pages(db: AsyncSession, document_id: int) -> list[Page]:
    """A document's pages as a reader takes them."""
    from app.services.documents.queries import pages_for

    return [
        {"page": page.page_number, "text": page.text}
        for page in await pages_for(db, document_id)
    ]
