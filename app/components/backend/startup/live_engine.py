"""Seed the live engines at startup when missing: Illiana's (#273), in
place of the template's defaults.

Engines are table data; a missing row is added from the seeds, one still
holding a former default takes the current one, an edited one is left
alone. A missing table (migrations not yet run) must not stop
the app from booting.
"""

from typing import Any

from app.core.log import logger


async def startup_hook() -> Any:
    from app.core.db import get_async_session
    from app.services.ai.service import live_engines
    from app.services.finance.service import ENGINE_SEEDS

    try:
        async with get_async_session() as session:
            added = await live_engines.seed_missing(session, ENGINE_SEEDS)
            refreshed = await live_engines.refresh_defaults(session)
    except Exception:
        logger.exception("Could not seed the live engines")
        return None
    if added:
        logger.info("Live engines seeded: %d", added)
    if refreshed:
        logger.info("Live engines given the current instructions: %d", refreshed)
    return None
