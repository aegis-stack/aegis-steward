"""Chat's work off the request path, as worker tasks (arq form).

Registered in the system queue, each only where what it reaches is. The
bodies import the AI service lazily, as ``document_tasks`` imports
documents.
"""

from typing import Any


async def announce_approval_task(
    ctx: dict[str, Any],
    conversation_id: str,
    message: str,
    user_id: str,
) -> dict[str, Any]:
    """Tell a conversation what was approved (``finance.domains.writes.
    announce``): a turn is a model call, so clicking Approve never waits
    on one."""
    from app.core.config import settings
    from app.services.ai.service import AIService

    reply = await AIService(settings).chat(
        message, conversation_id=conversation_id, user_id=user_id
    )
    return {"conversation_id": conversation_id, "replied": bool(reply)}


async def read_photo_task(
    ctx: dict[str, Any], user_id: str, key: str, media_type: str, title: str
) -> dict[str, Any]:
    """Keep a picture shared in chat and read what it showed: a vision
    call, so never on the request path. Later turns read it with
    ``pasted``."""
    from app.services.ai.service import read_photo_job

    return {"key": key, "read": await read_photo_job(user_id, key, media_type, title)}


async def warm_chat_task(
    ctx: dict[str, Any], agent_slug: str | None, user_id: str
) -> int | None:
    """Read the chat's opening into the local model before anyone asks:
    a long prompt read, so never on the request path."""
    from app.services.ai.service import warm_chat_job

    return await warm_chat_job(agent_slug, user_id)


async def fold_conversation_task(
    ctx: dict[str, Any], conversation_id: str, upto: int
) -> bool:
    """Fold the turns that left a conversation's history window into its
    running summary: a model call, so never on the request path."""
    from app.services.ai.service import fold_conversation_job

    return await fold_conversation_job(conversation_id, upto)
