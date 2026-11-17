"""
AI service API router.

FastAPI router for AI chat endpoints implementing core chat functionality,
conversation management, and service status.
"""

from fastapi import (
    APIRouter,
    Depends,
)

from app.components.backend.api.ai import analytics, chat, speech, status
from app.components.backend.api.ai import memory as memory_routes
from app.core.config import settings


async def sync_active_model() -> None:
    """Adopt the stored model selection before serving a request.

    The selection is a database row, so it can be written by a different
    process than this one - the CLI, or another worker. Re-reading it here is
    what makes ``llm use`` and the Cloud Catalog tab take effect on the
    running server without a restart.
    """
    from app.services.ai.service import active_model

    # No catalog table yet reads as nothing applied: .env is in effect.
    # ``ai_service.config`` reads ``settings``, so what this applies is used.
    await active_model.sync_from_db(settings)


router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(sync_active_model)])


# Request/Response models


# Context modules and saved facts both live in their own module.
router.include_router(memory_routes.router, tags=["ai: memory"])


# The sub-routers carry no prefix, tags or dependencies of their own:
# include_router hands them this router's, so every path and every
# Depends stays exactly what it was before the split.
router.include_router(chat.router)
router.include_router(status.router)
router.include_router(analytics.router)
router.include_router(speech.router)
