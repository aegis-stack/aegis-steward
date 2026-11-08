"""Shared factories for the documents test suite: a filed paper with its
pages read, the way every reading test starts."""

from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession


def pages(*lines: str) -> list[dict[str, Any]]:
    """One read page holding ``lines``, for a reader called directly."""
    return [{"page": 1, "text": "\n".join(lines)}]


async def seed_paper(
    db: AsyncSession, *lines: str, title: str = "statement-9.pdf", **fields: Any
) -> Any:
    """A document with one read page holding ``lines``. ``fields`` set
    columns on the row (``kind``, ``document_date``)."""
    from app.services.documents.models import Document, DocumentPage

    text = "\n".join(lines)
    document = Document(
        title=title,
        filename=title,
        storage_key=f"testcase/{abs(hash(text))}.pdf",
        media_type="application/pdf",
        content_hash=f"testcase-paper-{abs(hash(text))}",
        size_bytes=9,
        **fields,
    )
    db.add(document)
    await db.flush()
    db.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            status="read",
            method="text",
            text=text,
        )
    )
    await db.flush()
    return document
