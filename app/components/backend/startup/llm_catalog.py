"""What the LLM catalog needs on boot, in one place.

Two questions, each asked only when the answer could be "nothing yet":
is the remote catalog populated, and - on an install with the inference
component - are the locally pulled tags registered. Both are guarded so a
dev hot-reload never re-runs a sync against a catalog that is already
current, and both treat an unreachable source as a warning, not a
failed boot.
"""

from sqlmodel import Session

from app.core.db import engine
from app.core.log import logger
from app.services.ai.service import (
    local_models_present,
    sync_llm_catalog,
)


async def seed_llm_catalog() -> None:
    """Sync whatever the picker would otherwise be missing."""
    with Session(engine) as session:
        # A fresh local stack's picker is empty without this (why:
        # ``local_models_present``).
        if local_models_present(session):
            logger.info("Local models already in the catalog")
            return
        result = await sync_llm_catalog(session, mode="chat", source="local")
        logger.info(f"Local models registered: {result.models_added} models")
