"""A local model's read of the chat's opening, done before anyone asks.

A local model reads a new conversation's whole opening (her prompt, her
tools) before its first word: Inkling took 141s over 36K tokens, then 0.4s
for every question after (2026-11-28). ``warm_chat`` reads it at startup
and on a model switch, on the worker, so the first question meets a warm
cache. On llama.cpp the read is also saved to disk, and a freshly loaded
model has it restored in 0.2s instead of read again; a changed prompt
reads only from where it changed, and is saved again.

The chat that is warmed names itself (``keep_warm``): one, the web chat.
"""

import re
from typing import Any

from pydantic_ai import Agent

from app.core.discovery import present
from app.core.log import logger
from app.services.ai.domains.chat.attachments import build_user_content
from app.services.ai.models import AIProvider, Conversation, MessageRole
from app.services.ai.models.provider_names import LOCAL_PROVIDERS

# Stands in for the first question: the opening before it is the same.
QUESTION = "Hello."
# A warm cache still reads the question's last few tokens again.
_SAVE_PAST = 64

_target: tuple[str | None, str] | None = None


def keep_warm(agent_slug: str | None, user_id: str) -> None:
    """The chat ``warm_chat`` reads ahead for: its agent, as ``user_id``."""
    global _target
    _target = (agent_slug, user_id)


async def enqueue_warm() -> None:
    """Hand the warm-up to the worker (at startup, after a model switch),
    which reads the model picked (``warm_chat`` skips a hosted one): at
    startup this process may not have applied it yet. Never fails its
    caller: the first question then reads the opening instead."""
    if _target is None:
        return
    try:
        from app.components.worker import pools
        from app.core.constants import QueueName

        await pools.enqueue_task("warm_chat_task", QueueName.SYSTEM, *_target)
    except Exception as exc:  # noqa: BLE001 - the app goes on regardless
        logger.warning(f"Could not queue the chat warm-up: {exc}")


def _engine(provider: str) -> Any:
    """llama.cpp's engine, which saves and restores a read; None elsewhere."""
    if provider != AIProvider.LLAMACPP or not present("app.components.inference"):
        return None
    from app.components.inference.llamacpp import LlamaCppEngine

    return LlamaCppEngine()


async def warm_chat(ai: Any, agent_slug: str | None, user_id: str) -> int | None:
    """Read the chat's opening into the local model's cache, as a first
    turn sends it (``_build_turn``), one token long and kept nowhere.
    The tokens it read, or None on a hosted model."""
    from app.services.ai.service.chat import held_agent

    config = ai.config
    if config.provider not in LOCAL_PROVIDERS:
        return None
    conversation = Conversation(
        id="warm-up", provider=config.provider, model=config.model
    )
    conversation.add_message(MessageRole.USER, QUESTION)
    agent_config = await held_agent(conversation, agent_slug, hand_over=False)
    setup = await ai._build_turn(conversation, agent_config, user_id=user_id)
    model = agent_config.model_id or config.model
    filename = re.sub(r"[^\w.-]", "_", model) + ".bin"

    engine = _engine(config.provider)
    # Only into a model just loaded: one in memory holds its own cache,
    # maybe a conversation's past the opening, which this would replace.
    if engine is not None and await engine.waiting_reason(model) == "loading":
        try:
            await engine.slot("restore", model, filename)
        except Exception as exc:  # noqa: BLE001 - none saved yet: read it
            logger.info(f"Chat warm-up: no saved read restored ({exc})")

    usage = None
    async with setup.agent.iter(
        build_user_content(setup.conversation_context, None),
        model_settings={"max_tokens": 1, "extra_body": {"id_slot": 0}},
    ) as run:
        async for node in run:
            if Agent.is_call_tools_node(node):
                usage = node.model_response.usage
                break
    read = 0 if usage is None else usage.input_tokens - usage.cache_read_tokens
    logger.info(f"Chat warm-up: {model} read {read} tokens")
    if engine is not None and read > _SAVE_PAST:
        try:
            await engine.slot("save", model, filename)
        except Exception as exc:  # noqa: BLE001 - kept in memory regardless
            logger.warning(f"Chat warm-up: the read was not saved ({exc})")
    return read
