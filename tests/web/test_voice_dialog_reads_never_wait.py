"""The chat's voice dialog never waits on its own write lock.

Its route reads the voice profiles through the request's session, which
then holds the write lock (``app.core.db`` begins IMMEDIATE). The live-call
rows read the model catalog and the vendors' marks through sessions of
their own: opened as writers, they waited the whole busy timeout behind the
request and failed it, a 500 (2026-11-21). A read takes no write lock
(``read_only``), so it cannot wait, whoever asks.
"""

from __future__ import annotations

import pytest

from app.components.web_frontend.chat_surface import marks
from app.services.ai.domains.llm.catalog import list_models


@pytest.mark.usefixtures("holder")
async def test_the_catalog_read_does_not_wait() -> None:
    assert await list_models(mode="realtime") == []


@pytest.mark.usefixtures("holder")
async def test_the_vendor_marks_read_does_not_wait() -> None:
    assert await marks({"openai": ("openai",)}) == {}
