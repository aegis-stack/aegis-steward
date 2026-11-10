"""AI fixture/seed data system.

Provides seed data for LLM vendors, models, pricing, and the default
agent registry row.
"""

from sqlmodel import Session

from app.services.ai.domains.chat.agent_loader import (
    DEFAULT_AGENT_SLUG,
    default_agent_config,
)
from app.services.ai.fixtures.agent_fixtures import attach_tools, load_agent_fixtures
from app.services.ai.fixtures.llm_fixtures import load_all_llm_fixtures
from app.services.ai.fixtures.memory_module_fixtures import (
    load_memory_module_fixtures,
)
from app.services.finance.service import (
    FINANCE_TOOL_GRANTS,
    load_finance_agent_fixtures,
    memory_module_definitions,
)


def load_agent_registry_fixtures(session: Session) -> dict[str, int]:
    """The agent registry alone: agents, memory modules, and tool rows.

    Split out from the full set because startup runs it on every boot: the
    LLM catalog fixtures are a much larger static seed and belong to their
    own (rarer) path.
    """
    counts = load_agent_fixtures(session)
    counts.update(load_memory_module_fixtures(session, memory_module_definitions()))

    # Service-owned agents seed alongside the default one: a project that has
    # the finance service gets its analyst without a second seeding step.
    counts.update(load_finance_agent_fixtures(session))

    # Every agent's tools in one pass, once every agent row exists: by name
    # and additive, so a database seeded before a grant picks it up on the
    # next boot.
    counts["tool_links"] = attach_tools(
        session,
        [(DEFAULT_AGENT_SLUG, default_agent_config().tool_names), *FINANCE_TOOL_GRANTS],
    )
    if counts["tool_links"]:
        session.commit()
    return counts


def load_all_ai_fixtures(session: Session) -> dict[str, int]:
    """Load every AI seed set (LLM catalog + agent registry)."""
    counts = load_all_llm_fixtures(session)
    counts.update(load_agent_registry_fixtures(session))
    return counts


__all__ = [
    "load_agent_fixtures",
    "load_agent_registry_fixtures",
    "load_all_ai_fixtures",
    "load_all_llm_fixtures",
]
