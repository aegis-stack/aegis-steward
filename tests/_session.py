"""The one way a test hands the app's session openers its own session, and
reads back what landed in it."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


async def rows_of(db: AsyncSession, model: Any) -> list[Any]:
    """Every row of ``model``, for a test reading back what it wrote."""
    return list((await db.exec(select(model))).all())


def opens(
    session: AsyncSession,
) -> Callable[..., AbstractAsyncContextManager[AsyncSession]]:
    """A stand-in for ``get_async_session`` that yields ``session``, as a
    reader or a writer: ``monkeypatch.setattr(module, "get_async_session",
    opens(session))``."""

    @asynccontextmanager
    async def opener(read_only: bool = False) -> AsyncIterator[AsyncSession]:
        yield session

    return opener
