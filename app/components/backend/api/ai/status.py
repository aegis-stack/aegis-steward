"""Is the AI service up, and what is it running."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.api.ai.service import ai_service
from app.core.db import get_async_db
from app.core.log import logger
from app.services.ai.service import conversation_stats

router = APIRouter()


@router.get("/health")
async def ai_health(db: AsyncSession = Depends(get_async_db)) -> dict[str, Any]:
    """
    AI service health endpoint.

    Returns comprehensive health status including configuration,
    conversation count, and service availability.
    """
    try:
        status = await ai_service.get_service_status()
        said = await conversation_stats(db)
        validation_errors = await ai_service.validate_service()

        return {
            "service": "ai",
            "status": "healthy" if not validation_errors else "unhealthy",
            "enabled": status["enabled"],
            "provider": status["provider"],
            "model": status["model"],
            "agent_ready": status["agent_initialized"],
            "total_conversations": said.total_conversations,
            "configuration_valid": status["configuration_valid"],
            "validation_errors": validation_errors,
        }

    except Exception:
        # Logged, not returned: the text can carry paths, keys or SQL.
        logger.exception("AI health check failed")
        return {
            "service": "ai",
            "status": "error",
            "error": "AI service status unavailable",
        }


@router.get("/version")
async def ai_version() -> dict[str, Any]:
    """AI service version and feature information."""
    return {
        "service": "ai",
        "engine": "pydantic-ai",
        "version": "1.0",
        "features": [
            "chat",
            "conversation_management",
            "multi_provider_support",
            "health_monitoring",
            "api_endpoints",
            "cli_commands",
        ],
        "providers_supported": [
            "openai",
            "anthropic",
            "google",
            "groq",
            "mistral",
            "cohere",
        ],
    }
