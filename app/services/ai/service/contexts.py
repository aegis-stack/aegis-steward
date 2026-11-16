"""Per-request context builders: the model catalog.

Nothing that moves each turn (live health, usage counts) goes in the
system prompt: it leads every request, so a moving number makes a local
engine re-read the whole prompt every message. The ``health`` tool reads
those. Failures degrade to ``None`` rather than failing the chat turn.
"""

from app.core.db import get_async_session
from app.core.log import logger
from app.services.ai.domains.chat.llm_catalog_context import get_llm_catalog_context
from app.services.ai.service.usage import UsageMixin


class ContextsMixin(UsageMixin):
    """Builders for the dynamic context blocks injected per request."""

    async def _build_catalog_context(self) -> str | None:
        """
        Build LLM catalog context from database.

        Provides Illiana with awareness of available LLM models,
        their pricing, and capabilities.

        Returns:
            Formatted catalog context string, or None if unavailable
        """

        try:
            async with get_async_session() as session:
                return await get_llm_catalog_context(session)
        except Exception as e:
            logger.debug(f"Failed to build catalog context: {e}")
            return None
