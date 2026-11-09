"""The plan to retirement's assumptions as a card: ``plan.save`` (#353).

The Projected page's form states them; this is the same act proposed
by the assistant and approved like every other write. It runs the
function the page runs, so a plan changed by a card and one changed by
hand are changed the same way. Only what is sent changes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.formatting import before_and_after
from app.core.schema import require_one_of
from app.services.finance.domains.detection.insights.formatting import (
    format_apr,
    format_usd,
)
from app.services.finance.domains.planning.retirement import TYPES, label
from app.services.finance.domains.writes.registry import ChangeExecutor
from app.services.finance.schemas import ChangeDisplayRow


class PlanSavePayload(BaseModel):
    """What the household states about itself and its money; any of it."""

    model_config = ConfigDict(extra="forbid")

    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    retire_age: int | None = Field(default=None, ge=18, le=120)
    end_age: int | None = Field(default=None, ge=18, le=120)
    returns_bps: dict[str, int] | None = None  # a year, by type
    volatility_bps: dict[str, int] | None = None  # a year, by type
    contributions_cents: dict[str, int] | None = None  # a month, by type
    spending_cents: int | None = Field(default=None, ge=0)  # a month, retired

    @field_validator("returns_bps", "volatility_bps", "contributions_cents")
    @classmethod
    def _known_types(cls, given: dict[str, int] | None) -> dict[str, int] | None:
        for kind in given or ():
            require_one_of(kind, TYPES)
        return given

    @model_validator(mode="after")
    def _says_something(self) -> PlanSavePayload:
        if not self.changes():
            raise ValueError("Nothing to change: give at least one field.")
        return self

    def changes(self) -> dict[str, Any]:
        """In ``plan.amend_plan``'s field names."""
        named = {
            "birth_year": self.birth_year,
            "retire_age": self.retire_age,
            "end_age": self.end_age,
            "returns": self.returns_bps,
            "volatility": self.volatility_bps,
            "contributions": self.contributions_cents,
            "spending": self.spending_cents,
        }
        return {name: value for name, value in named.items() if value is not None}


# How each figure reads on the card, and for one by type, the reader
# on Assumptions that says what stands.
_SAID: dict[str, Any] = {
    "birth_year": str,
    "retire_age": str,
    "end_age": str,
    "spending": format_usd,
    "returns": format_apr,
    "volatility": format_apr,
    "contributions": format_usd,
}
_READERS = {"returns": "rate", "volatility": "swing", "contributions": "contribution"}


async def plan_save_execute(
    db: AsyncSession, payload: PlanSavePayload, owner_user_id: int | None
) -> dict[str, Any]:
    from app.services.finance.domains.planning.plan import amend_plan
    from app.services.finance.utils import current_date

    changes = payload.changes()
    # The path is saved off the line alone; the band is drawn on the page.
    await amend_plan(
        db, owner_user_id=owner_user_id, today=current_date(), changes=changes, runs=1
    )
    return {"changed": sorted(changes)}


async def plan_save_describe(
    db: AsyncSession, payload: PlanSavePayload, owner_user_id: int | None
) -> list[ChangeDisplayRow]:
    """Each figure sent that moves, before and after: what stands is
    what the plan runs on today, measured where nothing was stated."""
    from app.services.finance.domains.planning.plan import (
        plan_inputs,
        stated_assumptions,
    )
    from app.services.finance.domains.planning.queries import plan_row
    from app.services.finance.utils import current_date

    today = current_date()
    stated = stated_assumptions(
        await plan_row(db, owner_user_id),
        await plan_inputs(db, owner_user_id=owner_user_id, today=today),
    )
    pairs: list[tuple[str, Any, Any, Any]] = []
    for name, now in payload.changes().items():
        if name in _READERS:
            standing = getattr(stated, _READERS[name])
            pairs += [
                (label(name, k), _SAID[name], standing(k), v) for k, v in now.items()
            ]
        else:
            pairs.append((label(name), _SAID[name], getattr(stated, name), now))
    rows = [
        ChangeDisplayRow(
            label=named,
            value=before_and_after(said(was) if was is not None else "", said(now)),
        )
        for named, said, was, now in pairs
        if was != now
    ]
    if not rows:
        raise ValueError("This would change nothing about the plan.")
    return rows


# Registered by ``executors``, which arms every change type.
CHANGES = (
    ChangeExecutor(
        change_type="plan.save",
        title="Change the plan to retirement",
        payload_model=PlanSavePayload,
        execute=plan_save_execute,
        describe=plan_save_describe,
    ),
)
