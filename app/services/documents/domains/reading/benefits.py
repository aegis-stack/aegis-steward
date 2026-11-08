"""The retirement income a statement estimates (#352).

A Social Security statement says what it will pay at 67; a pension
statement says what it will pay and from when. Both sat on the shelf as
paper while the plan to retirement had no income in it. A labelled
line, the way every other reading here works: the figure after the
words that say it is a monthly benefit, and the age or the date beside
it.

Only lines that SAY they are a benefit. A statement is full of money,
and a balance read as a benefit is a pension that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.domains.reading.figures import labelled, money_in
from app.services.documents.domains.reading.findings import Page
from app.services.documents.domains.reading.metadata import OPENING_PAGES
from app.services.documents.domains.reading.patterns import find_date

# The card this reading proposes: the Bills page's own "declare an
# income", so approving it runs the executor that exists.
DECLARE = "recurring.declare"

BENEFIT_LABELS = (
    "estimated monthly benefit",
    "monthly retirement benefit",
    "monthly pension benefit",
    "monthly pension",
    "monthly benefit",
    "monthly annuity",
    "benefit amount",
)
_LABEL = re.compile(r"\b(" + "|".join(BENEFIT_LABELS) + r")\b", re.I)
_AGE = re.compile(r"\bat (?:age |full retirement age,? )?(\d{2})\b", re.I)
_SOCIAL_SECURITY = re.compile(r"social security", re.I)


@dataclass(frozen=True)
class Benefit:
    """What a statement says it will pay a month, and from when: an age
    (Social Security's way) or a date (a pension's)."""

    monthly_cents: int
    kind: str
    start_age: int | None
    starts: date | None


def benefits(pages: list[Page]) -> Benefit | None:
    """The benefit this document states, or nothing. The first labelled
    line wins: a statement leads with what it is about."""
    front = "\n".join(p["text"] or "" for p in pages[:OPENING_PAGES])
    kind = "social_security" if _SOCIAL_SECURITY.search(front) else "pension"
    for _page, said, tail in labelled(pages, _LABEL):
        cents = money_in(tail)
        if cents is None:
            continue
        age = _AGE.search(said)
        found = find_date(said)
        return Benefit(
            cents,
            kind,
            int(age.group(1)) if age else None,
            found[0] if found else None,
        )
    return None


async def propose_benefit(
    db: AsyncSession, document_id: int, owner_user_id: int | None
) -> Any | None:
    """The benefit a statement estimates, as the income stream it will
    be: monthly, from the day it starts, marked as the pension or Social
    Security it is so the plan counts it from then.

    The start has to be a day somebody can name: the date printed, or
    the age printed read against the plan's birth year. Neither means
    no card - a stream that starts "at 67" for a household that never
    said when 67 is would start today.
    """
    from app.services.documents.domains.reading.proposals import (
        PROPOSED_BY,
        _already_asked,
        _read_pages,
    )
    from app.services.finance.service import INCOME_KINDS, plan_row, propose

    read = await _read_pages(db, document_id)
    found = benefits(read)
    if found is None:
        return None
    starts = found.starts
    if starts is None and found.start_age is not None:
        plan = await plan_row(db, owner_user_id)
        if plan is not None and plan.birth_year:
            starts = date(plan.birth_year + found.start_age, 1, 1)
    if starts is None:
        return None
    if await _already_asked(db, DECLARE, document_id):
        return None
    return await propose(
        db,
        DECLARE,
        {
            "name": INCOME_KINDS[found.kind],
            "direction": "inflow",
            "frequency": "monthly",
            "amount_cents": found.monthly_cents,
            "next_expected_date": starts.isoformat(),
            "income_kind": found.kind,
            "document_id": document_id,
        },
        owner_user_id=owner_user_id,
        proposed_by_agent=PROPOSED_BY,
    )
