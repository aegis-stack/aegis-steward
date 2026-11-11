"""Agent registry seed data.

Seeds the default ``assistant`` agent so a fresh project behaves exactly
like pre-registry chat: same system prompt, same sampling defaults. The
agent loader resolves this row on DB backends and falls back to the same
in-code definition on the memory backend, so this seed is the single DB
source of the default agent.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from sqlmodel import Session, col, select

from app.core.log import logger
from app.core.seed import seed_rows
from app.core.tools import get_tool, load_tools, registered_tool_names
from app.services.ai.domains.chat.agent_loader import (
    DEFAULT_AGENT_SLUG,
    default_agent_config,
)
from app.services.ai.domains.chat.agent_registry import seed_agent
from app.services.ai.models.agents import Agent, AgentTool, Tool

# The registry only holds tools whose module was imported, and seeding runs
# in processes that never build a chat agent (a CLI, a startup hook):
# without this the sync writes no rows and every later grant silently no-ops.
load_tools()

__all__ = [
    "DEFAULT_AGENT_SLUG",
    "attach_tools",
    "default_agent_definition",
    "load_agent_fixtures",
]


def attach_tools(session: Session, grants: Iterable[tuple[str, Sequence[str]]]) -> int:
    """Grant each agent (``(slug, tool names)``, a slug named twice gets
    both lists) the tools it lacks, every agent's in one pass, and say how
    many: additive and by name (``seed_rows``), so a re-seed grants what a
    newer definition added and never takes back what someone else attached.
    A tool with no row (not registered here) is skipped with a warning. The
    caller commits."""
    grants = list(grants)
    agents = dict(
        session.exec(
            select(Agent.slug, Agent.id).where(
                col(Agent.slug).in_({s for s, _ in grants})
            )
        ).all()
    )
    wanted = {name for _, names in grants for name in names}
    tools = dict(
        session.exec(select(Tool.name, Tool.id).where(col(Tool.name).in_(wanted))).all()
    )
    for name in sorted(wanted - tools.keys()):
        logger.warning(f"Tool row missing, not granted: {name}")
    links = [
        {"agent_id": agents[slug], "tool_id": tools[name]}
        for slug, names in grants
        if slug in agents
        for name in names
        if name in tools
    ]
    return seed_rows(
        session,
        AgentTool,
        ("agent_id", "tool_id"),
        links,
        col(AgentTool.agent_id).in_(agents.values()),
    )


def default_agent_definition() -> dict[str, Any]:
    """The seed row for the default agent.

    Built from the loader's in-code config so the DB source and the
    memory-mode fallback can never drift: same prompt, same sampling
    values (captured from settings at seed time).
    """
    config = default_agent_config()
    return {
        "slug": config.slug,
        "name": config.name,
        "description": "Default conversational agent",
        "category": "general",
        "model_id": config.model_id,
        "system_prompt": config.system_prompt,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "memory_modules": list(config.memory_modules),
        "knowledge_base_ids": list(config.knowledge_base_ids),
        "is_active": True,
        "code_mode": config.code_mode,
    }


def load_agent_fixtures(session: Session) -> dict[str, int]:
    """Seed the default agent and the registry's tool rows, skipping rows
    that already exist. Its tools are granted with every other agent's
    (``load_agent_registry_fixtures``).

    Idempotent: re-running against a seeded database adds nothing. An
    existing (possibly user-edited) row is never rewritten.

    Args:
        session: Database session

    Returns:
        dict with counts: {"agents", "tools": N added}
    """
    added = 0
    definition = default_agent_definition()
    existing = session.exec(
        select(Agent).where(Agent.slug == definition["slug"])
    ).first()
    if existing is None:
        seed_agent(session, definition)
        session.commit()
        added = 1
        logger.info(f"Seeded default agent '{definition['slug']}'")
    else:
        logger.debug(f"Default agent '{definition['slug']}' already present")

    # Sync registered tools into grantable rows: every callable in the
    # Python registry gets a matching ``tool`` row (by name) so the agent
    # CRUD can attach it. A stale row is never deleted; it degrades to a
    # skipped-name warning at resolve time.
    tool_rows = []
    for name in registered_tool_names():
        entry = get_tool(name)
        tool_rows.append(
            {"name": name, "description": entry.description if entry else None}
        )
    tools_added = seed_rows(session, Tool, "name", tool_rows)
    if tools_added:
        session.commit()
        logger.info(f"Seeded {tools_added} tool row(s) from the registry")
    return {"agents": added, "tools": tools_added}
