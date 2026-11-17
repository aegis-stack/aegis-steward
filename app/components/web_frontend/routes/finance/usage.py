"""Settings > Usage (#270): what models and voice cost.

One page over the one ledger: chat and agent turns, live calls, hearing
and speaking, by kind and by model, and each live call as its minutes
plus the answers given during it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.responses import Response

from app.components.web_frontend import ranges
from app.components.web_frontend.filters import short_date, usd
from app.components.web_frontend.nav import section, settings_nav
from app.components.web_frontend.rendering import render
from app.core.db import get_async_db
from app.core.formatting import format_minutes
from app.services.ai.service import spend_report

router = APIRouter()

SECTION = section("settings")
USAGE = SECTION.path + "/usage"
DEFAULT_DAYS = 30
# "All" reads back ten years, the ceiling the API's windows use.
_ALL_DAYS = 3650
WINDOWS = tuple(w for w in ranges.WINDOWS if w[0] != 1)

MODEL_COLUMNS = [
    {"key": "kind", "label": "Kind"},
    {"key": "model", "label": "Model"},
    {"key": "uses", "label": "Uses", "align": "right"},
    {"key": "minutes", "label": "Minutes", "align": "right"},
    {"key": "tokens", "label": "Tokens", "align": "right"},
    {"key": "cost", "label": "Cost", "align": "right"},
]
CALL_COLUMNS = [
    {"key": "when", "label": "When"},
    {"key": "minutes", "label": "Minutes", "align": "right"},
    {"key": "call_cost", "label": "Call", "align": "right"},
    {"key": "answers_cost", "label": "Her answers", "align": "right"},
    {"key": "total", "label": "Total", "align": "right"},
    {"key": "ended", "label": "Ended"},
]


@router.get(USAGE, include_in_schema=False)
async def usage(
    request: Request,
    days: int = DEFAULT_DAYS,
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    # The ledger stores naive UTC; the window reads it the same way.
    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=_ALL_DAYS if days == ranges.ALL else days)
    models = await spend_report.models_by_kind(db, start, end)
    calls = await spend_report.live_calls(db, start, end)
    kinds: dict[str, dict[str, float]] = {}
    for row in models:
        kind = kinds.setdefault(row.kind, {"cost": 0.0, "uses": 0, "seconds": 0.0})
        kind["cost"] += row.cost
        kind["uses"] += row.uses
        kind["seconds"] += row.seconds
    return render(
        request,
        "pages/settings/usage.html",
        {
            "section": SECTION,
            **settings_nav("usage"),
            "path": USAGE,
            "days": days,
            "ranges": WINDOWS,
            "total": usd(sum(kind["cost"] for kind in kinds.values())),
            "kinds": [
                {
                    "label": label,
                    "value": usd(kind["cost"]),
                    "caption": (
                        f"{format_minutes(kind['seconds'])} min · {int(kind['uses'])} uses"
                        if kind["seconds"]
                        else f"{int(kind['uses'])} uses"
                    ),
                }
                for label, kind in kinds.items()
            ],
            "model_columns": MODEL_COLUMNS,
            "models": [
                {
                    "kind": m.kind,
                    "model": m.model_id,
                    "uses": m.uses,
                    "minutes": format_minutes(m.seconds) or "",
                    "tokens": f"{m.tokens:,}" if m.tokens else "",
                    "cost": usd(m.cost),
                }
                for m in models
            ],
            "call_columns": CALL_COLUMNS,
            "calls": [
                {
                    "when": short_date(call.started),
                    "minutes": format_minutes(call.seconds) or "",
                    "call_cost": usd(call.call_cost),
                    "answers_cost": usd(call.answers_cost),
                    "total": usd(call.call_cost + call.answers_cost),
                    "ended": spend_report.ENDED[call.success],
                }
                for call in calls
            ],
        },
    )
