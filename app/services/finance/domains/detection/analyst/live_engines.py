"""Illiana's live engines, seeded into ``live_engine`` when missing (#273).

Each names its model by catalog id (``large_language_model.model_id``);
the name, maker and price are the catalog's.

The rows are the app's once seeded: an edit (a tighter cap, other
instructions) is never overwritten. A new engine is a new entry here.
Seeded in place of the template's defaults (``startup/live_engine.py``):
the same keys, with her finance instructions.
"""

from typing import Any

from app.services.finance.domains.detection.analyst.prompts import (
    FINANCE_LIVE_INSTRUCTIONS,
    FINANCE_REALTIME_INSTRUCTIONS,
)

# A realtime reply's hard cap. Output tokens include her speech's audio
# (~1,200 a minute) and any run_code script she writes, so this is a
# backstop against a monologue, not the brevity itself - the instructions
# are that.
REALTIME_REPLY_CAP = 1_200


ENGINE_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "key": "gpt-live",
        "model": "gpt-live-1",
        "note": "full duplex, hums while she works; billed by the minute plus her answers",
        "instructions": FINANCE_LIVE_INSTRUCTIONS,
        "sort_order": 0,
    },
    {
        "key": "gpt-realtime-2.1",
        "model": "gpt-realtime-2.1",
        "note": "turn-taking, her agent's own brain; billed by its tokens",
        "instructions": FINANCE_REALTIME_INSTRUCTIONS,
        "max_output_tokens": REALTIME_REPLY_CAP,
        "sort_order": 1,
    },
    {
        "key": "gpt-realtime-2.1-mini",
        "model": "gpt-realtime-2.1-mini",
        "note": "turn-taking, cheapest",
        "warning": "cannot use her code mode yet (spike, #272)",
        "instructions": FINANCE_REALTIME_INSTRUCTIONS,
        "max_output_tokens": REALTIME_REPLY_CAP,
        "sort_order": 2,
    },
    {
        "key": "gemini-live",
        "model": "gemini-3.8-live",
        "note": "turn-taking, her agent's own brain; billed by its tokens",
        "instructions": FINANCE_REALTIME_INSTRUCTIONS,
        "max_output_tokens": REALTIME_REPLY_CAP,
        "sort_order": 3,
    },
)


# Her realtime manners and every default they have had, by digest, for the
# startup's refresh (``live_engines.refresh_defaults``) beside the
# template's: an engine still holding one was never edited, so it takes the
# current. They follow the template's, so a change to either adds the old
# digest here (the pinned digest in the tests says when).
HER_REALTIME_DEFAULTS = (
    FINANCE_REALTIME_INSTRUCTIONS,
    frozenset(
        {
            "e5eeb64025208848811658fedfa7ea0461b9846b6869d3673bbee2bdbdda4ae0",
            "66196909b835d4619994a9e57fa566dbd0b1332912c51e9f20ca91c8286eafdd",
        }
    ),
)
