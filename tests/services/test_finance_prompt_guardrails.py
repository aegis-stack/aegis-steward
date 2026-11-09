"""What she says about herself (#273).

On a realtime call she read her own context check aloud ("256 older
messages fell out of my current view"). How she works - her context,
prompt, tools, sandbox - is not something to volunteer, anywhere she
talks. One rule, in her base chat prompt (which her voice agent and a
realtime engine's prompt extend) and in GPT-Live's own persona.
"""

from __future__ import annotations

import asyncio

from app.services.finance.domains.detection.analyst.prompts import (
    ABOUT_YOURSELF,
    FINANCE_CHAT_SYSTEM_PROMPT,
    FINANCE_LIVE_INSTRUCTIONS,
)


def test_her_base_prompt_keeps_the_machinery_to_herself() -> None:
    assert ABOUT_YOURSELF in FINANCE_CHAT_SYSTEM_PROMPT


def test_gpt_live_keeps_it_to_itself_too() -> None:
    assert ABOUT_YOURSELF in FINANCE_LIVE_INSTRUCTIONS


def test_she_can_still_explain_it_when_asked() -> None:
    assert "unless they ask" in ABOUT_YOURSELF


def test_what_she_may_propose_is_read_from_code_each_turn() -> None:
    """Her row is seeded once and never re-read from code, so a change
    type registered after that reached nobody - three times. The
    catalog is a memory module now, rendered from the registry's own
    prompt text on every turn; the row keeps only who she is."""
    from app.services.ai.service import FetchContext
    from app.services.finance.domains.detection.analyst.prompt_changes import (
        PROPOSING_CHANGES,
    )
    from app.services.finance.domains.detection.analyst.report import (
        proposing_changes,
    )
    from app.services.finance.domains.detection.analyst.seeds import (
        finance_chat_agent_definition,
        memory_module_definitions,
    )
    from app.services.finance.domains.detection.analyst.shared import (
        CHANGES_MODULE_SLUG,
    )

    assert "## PROPOSING CHANGES" not in FINANCE_CHAT_SYSTEM_PROMPT
    assert CHANGES_MODULE_SLUG in finance_chat_agent_definition()["memory_modules"]
    (module,) = [
        m for m in memory_module_definitions() if m["slug"] == CHANGES_MODULE_SLUG
    ]
    assert (
        module["fetch_function"] == CHANGES_MODULE_SLUG and not module["prompt_content"]
    )
    assert (
        asyncio.run(proposing_changes(FetchContext(user_id="1"))) is PROPOSING_CHANGES
    )


def test_every_registered_change_type_is_advertised() -> None:
    """A card she cannot name is a card she will say the app cannot make."""
    from app.services.finance.domains import writes
    from app.services.finance.domains.detection.analyst.prompt_changes import (
        PROPOSING_CHANGES,
    )

    # Registered change types she never files herself: a reader's cards
    # (a scan matched to its row, a receipt to its charge), the shelf's
    # combine, and the memory cards her memory TOOLS file.
    not_hers = {
        "check.attach",
        "receipt.attach",
        "document.combine",
        "memory.save",
        "memory.update",
        "memory.replace",
        "memory.forget",
    }
    registered = set(writes.registered_change_types())
    assert not_hers <= registered, not_hers - registered
    missing = [
        change_type
        for change_type in registered - not_hers
        if f"`{change_type}`" not in PROPOSING_CHANGES
    ]
    assert missing == []


def test_a_match_is_not_confined_to_the_shortlist() -> None:
    """Told to take ids "ONLY" from bill_candidates, she refused the gym
    payment she had just read aloud - a detector's twin of the bill held
    it, so the shortlist never offered it. The shortlist is where to
    look first; a payment transactions() found is as good an id."""
    from app.services.finance.domains.detection.analyst.prompt_changes import (
        PROPOSING_CHANGES,
    )

    match = PROPOSING_CHANGES.split("`recurring.match`", 1)[1].split("\n- `", 1)[0]
    assert "transactions(" in match
    assert "ONLY" not in match
