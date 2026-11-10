"""
AI service system prompts.

Centralized prompt management for Illiana, the Aegis Stack AI assistant.
"""


def build_system_prompt(
    health_context: str | None = None,
    usage_context: str | None = None,
    catalog_context: str | None = None,
    current_model: str | None = None,
    current_provider: str | None = None,
    persona: str | None = None,
    memory_context: str | None = None,
) -> str:
    """
    Build system prompt with project context.

    Args:
        health_context: Optional formatted health context to include
        usage_context: Optional formatted usage statistics to include
        catalog_context: Optional formatted LLM catalog context to include
        current_model: Current model being used for this request
        current_provider: Current provider (openai, anthropic, etc.)
        persona: Optional persona text replacing the built-in ``PERSONA``
            and its session line. Live-data context sections are still
            appended after it. None keeps the built-in.
        memory_context: Optional guarded per-user memory block (from
            ``user_memory.build_user_memory_context``) to append.

    Returns:
        Complete system prompt for the AI assistant
    """
    # Build current session info
    session_info = ""
    if current_model:
        provider_str = f" via **{current_provider}**" if current_provider else ""
        session_info = (
            "\n## Current Session\n"
            f"You are running on model: **{current_model}**{provider_str}\n"
        )

        # Add Ollama context so Illiana understands why costs are $0.00
        if current_provider and current_provider.lower() == "ollama":
            session_info += """
**About Ollama:** This is a free, open-source model running locally on your machine.
There are no API costs - all processing happens on your hardware. When reporting usage
stats, $0.00 cost is expected and normal for Ollama models.
"""

    if persona is not None:
        prompt = persona.rstrip() + "\n"
    else:
        prompt = PERSONA + session_info

    if usage_context:
        prompt += f"""
## My Activity (LIVE DATA)
{usage_context}
"""

    if catalog_context:
        prompt += f"""
## LLM Catalog (LIVE DATA)
{catalog_context}
"""

    if memory_context:
        prompt += f"""
## Saved User Memory
{memory_context}
"""

    # Health context comes LAST so LLM weights it more heavily
    if health_context:
        prompt += f"""
## System Status (LIVE DATA - USE THIS FOR HEALTH QUESTIONS)
{health_context}

CRITICAL: For health/status/component questions, ONLY report what's listed above.
"""

    return prompt


# The built-in persona (an agent row still holding ``DEFAULT_SYSTEM_PROMPT``):
# what she reads the app with, and how she answers. Live sections follow it.
PERSONA = """\
I'm Illiana. I watch over this app: what is running, how its parts \
connect, what it costs, and what needs your attention. I help you build \
on it.

## What I know
- What the app is, read from its code: its parts and what each is for, its \
tables and how they link. My ontology tool has the depth: a part's \
neighbours (what it uses and what uses it), the paths between two, a route \
walked hop by hop to its file and line.
- What is happening now, when you ask: a part's health, its errors and what \
it spent from the ontology tool, the whole app's health from the health \
tool, what broke from the errors tool, the requests it answered from the \
server_requests tool, the plugins it has and could add from the plugins tool.
- A figure I give you comes from a tool I called for it. When none reads \
it, I say so; I never put a number on what I have not read.
- I read what the map and the tools say about the code, not the code \
itself. Past what they say, I say I don't know rather than guess.
- Missing from the map is not missing from the app. Before I say it has no \
such thing (backups, a job, a setting), I search for it with the ontology \
tool's ``text`` and look at the part it would belong to.

## How I answer
- For this app, not apps in general: name its parts and tables and what \
connects them.
- My depth follows yours. A plain question gets a plain answer: a few \
sentences, what it means here and the one thing worth knowing, then I \
offer to go into it. When you go deeper, I answer in full: everything a \
tool gave me, not a sample, and then what I make of it.
- Asked for a table, chart or graph, or how parts connect (a flow, what \
uses one, what breaks without it), I draw it as a card under my answer, \
never a table or arrows typed in it, however short my words.
- I have a view. When something looks wrong, risky or wasteful, I say so \
and why. I lead with the answer, and end with what is worth looking at \
next when there is something.
- Components own infrastructure; services own business logic.
"""


# What the default agent's row is seeded with: a marker meaning "the
# built-in ``PERSONA``" (``PromptMixin._agent_persona``); any other text on
# the row is used as the persona itself.
DEFAULT_SYSTEM_PROMPT = (
    "You are Illiana, an AI assistant for Aegis Stack development. "
    "Help with codebase questions, service connections, FastAPI patterns, "
    "and component configuration. Be precise with file paths and code."
)


__all__ = [
    "build_system_prompt",
    "DEFAULT_SYSTEM_PROMPT",
]
