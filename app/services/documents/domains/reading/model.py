"""The one way a reader hands a page to the model.

A letter's demands (``letters``) and an order's items (``orders``) are
read by a model with a typed output; what they do with the answer is
their own, but the call - the active model, the usage recorded against
the surface, the pages written out with their numbers - is one call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from app.services.documents.domains.reading.findings import PAGE_HEADING, Page

T = TypeVar("T", bound=BaseModel)


def pages_text(pages: list[Page]) -> str:
    """The pages as the model is handed them, each under its number, so
    a reading can cite the page it read."""
    return "\n\n".join(
        PAGE_HEADING.format(number=page["page"]) + str(page["text"])
        for page in pages
        if page["text"]
    )


async def read_with_model(
    prompt: str, *, instructions: str, output_type: type[T], surface: str
) -> T:
    """Hand the text to the active model and take back its typed reading."""
    from pydantic_ai import Agent as PydanticAgent

    from app.core.config import settings
    from app.services.ai.service import active_model, extract_usage, record_usage

    model, model_name = await active_model.model_for_active(settings)
    agent: PydanticAgent[None, T] = PydanticAgent(
        model, instructions=instructions, output_type=output_type
    )
    result = await agent.run(prompt)
    await record_usage(
        action=surface, model_name=model_name, usage=extract_usage(result), user_id=None
    )
    return result.output


async def when_reachable(read: Callable[..., Awaitable[Any]]) -> Any:
    """``read``, or None when no model is reachable: a stack without the
    AI service reads paper by pattern and proposes its metadata as
    before; only what needs a model goes unread."""
    from app.core.config import settings
    from app.services.ai.service import ProviderSetupError, active_model

    try:
        await active_model.model_for_active(settings)
    except ProviderSetupError:
        return None
    return read
