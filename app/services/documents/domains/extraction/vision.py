"""The vision reader extraction hands a rendered page to.

The same model the chat surface reads a pasted screenshot with, called
headlessly: an image in, its text out. ``look`` is the one call; a page
of paper and a picture shared in chat (``pastes.read_photo``) differ only
in what the model is told and where the usage is recorded, so the cost
of reading paper stays visible on its own.
"""

from __future__ import annotations

import time

from app.core.config import settings
from app.services.ai.service import (
    active_model,
    extract_usage,
    record_usage,
)
from app.services.documents.domains.extraction.pages import VisionReader

SURFACE = "documents:extract"
INSTRUCTIONS = (
    "You transcribe one page of a scanned document. Return the page's text "
    "faithfully in reading order, keeping headings, labels, amounts, dates "
    "and account numbers exactly as printed. Render tables one row per "
    "line with cells separated by ' | '. Do not summarize, interpret, or add "
    "anything that is not on the page."
)


async def look(
    image: bytes, media_type: str, *, instructions: str, ask: str, surface: str
) -> tuple[str, str]:
    """One image through the active model; returns (text, model name).
    Usage is recorded under ``surface``."""
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.messages import BinaryContent

    model, model_name = await active_model.model_for_active(settings)
    agent: PydanticAgent[None, str] = PydanticAgent(model, instructions=instructions)
    started = time.perf_counter()
    result = await agent.run([ask, BinaryContent(data=image, media_type=media_type)])
    await record_usage(
        action=surface,
        model_name=model_name,
        usage=extract_usage(result),
        user_id=None,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    return str(result.output), model_name


async def read_page(image: bytes, media_type: str) -> tuple[str, str]:
    """Transcribe one page image; returns (text, model name)."""
    return await look(
        image,
        media_type,
        instructions=INSTRUCTIONS,
        ask="Transcribe this page.",
        surface=SURFACE,
    )


async def vision_reader() -> VisionReader | None:
    """The reader, or None when the provider in force cannot hand out
    a bare model (the keyless public endpoints build their own client).

    Asks the selection that is actually active, not the .env bootstrap:
    a worker resolving the wrong provider would refuse to read a page the
    chosen model can see, or hand one to a model that cannot.
    """
    from app.services.documents.domains.reading.model import when_reachable

    return await when_reachable(read_page)
