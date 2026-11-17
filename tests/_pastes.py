"""A chat's kept pastes for a test: a read document or a photo, as a turn
leaves them in the user's index (``pastes.keep_paste``)."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.chat.pastes import (
    Paste,
    document_paste_id,
    keep_paste,
    paste_id,
)


async def keep_document(
    db: AsyncSession, user_id: str, document_id: int, title: str, chars: int
) -> Paste:
    return await keep_paste(
        db,
        user_id,
        Paste(
            id=document_paste_id(document_id),
            title=title,
            chars=chars,
            document_id=document_id,
        ),
    )


async def keep_photo(
    db: AsyncSession, user_id: str, key: str, media_type: str, title: str
) -> Paste:
    return await keep_paste(
        db,
        user_id,
        Paste(id=paste_id(key), key=key, media_type=media_type, title=title),
    )
