"""Read the chat's opening into a local model at startup (``chat.warm``),
on the worker: the first question then meets a warm cache, not minutes of
reading. Nothing on a hosted model."""

from typing import Any


async def startup_hook() -> Any:
    from app.services.ai.service import enqueue_warm

    await enqueue_warm()
