"""Durable readings: what the model extracted from an ephemeral image.

Attachment bytes ride one turn by design (see ``attachments.py``); the
EXTRACTION must not. ``record_reading`` is the schema-forced write the
agent calls the moment it reads a receipt, order, or document out of an
image: the payload validates against a Pydantic contract (bad rows
bounce back as a correctable tool error, the same door-guarding the
finance queue uses), stages inside the turn, and the turn's finalize
merges it into the USER's store. Every later turn re-injects the stored
readings as context, so "list the items again" works long after the
pixels are gone - and a model that forgets to narrate its reading no
longer loses it.

Keyed to the user, not the conversation, because "durable" has to mean
durable. Stored per conversation, twelve pages of extracted order
listings were invisible the moment a new thread was opened, and
recovering them meant reading them back out of the database by hand -
which is not a thing an app can ask anyone to do. The readings
live beside the saved facts in ``agent_user_memory``: one row per user,
already the home of everything an agent knows about them across
conversations.

Generic on purpose: any agent on any surface can record any kind of
reading ("receipt", "statement", "document"); nothing here belongs to
finance.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.core.figures import FIGURES
from app.core.tools import Refused, register_tool

# Bounded: readings are context re-injected EVERY turn, so an unbounded
# list would slowly crowd out the conversation itself. Oldest go first.
_MAX_READINGS_PER_USER = 8

# The turn's staging area; None outside a chat turn.
_staged: ContextVar[list[Reading] | None] = ContextVar("staged_readings", default=None)


class ReadingItem(BaseModel):
    """One extracted line: what it was, how many, what it cost - and
    which GROUP the source put it in (a shipment, a sub-receipt, a
    page). Groups are how items map to the right charge later; a
    flattened reading loses exactly that."""

    label: str = Field(min_length=1)
    quantity: int = Field(default=1, ge=1)
    amount_cents: int | None = Field(default=None, ge=0)
    group: str | None = None
    note: str | None = None


class Reading(BaseModel):
    """One recorded extraction from an attached image (or document): its
    line items, and the source's own fields - letterhead, address, phone,
    dates, totals, account numbers. A reading is the only copy of the
    image left (#286: a dentist's receipt kept the visit and lost the
    address and phone, so it took a re-upload)."""

    kind: str = "receipt"
    title: str = Field(min_length=1)
    items: list[ReadingItem] = Field(default_factory=list)
    fields: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _says_something(self) -> Reading:
        if not self.items and not self.fields:
            raise ValueError("a reading needs its line items, its fields, or both")
        return self


def kept_readings(raw: list[dict[str, Any]]) -> list[Reading]:
    """Readings as stored (the user's row, or a thread's legacy list)."""
    return [Reading.model_validate(r) for r in raw]


@contextmanager
def reading_stage() -> Iterator[list[Reading]]:
    """The turn wrapper: opens a staging list ``record_reading`` writes
    into; the caller merges it into the user's store after the run."""
    staged: list[Reading] = []
    token = _staged.set(staged)
    try:
        yield staged
    finally:
        _staged.reset(token)


class Recorded(BaseModel):
    """What a reading kept: how many items, under what title."""

    model_config = FIGURES

    recorded: int
    title: str


async def record_reading(
    title: str,
    items: list[dict[str, Any]],
    kind: str = "receipt",
    fields: dict[str, str] | None = None,
) -> Recorded | Refused:
    """Durably record what you just read out of an attached image.

    Call this THE MOMENT you finish reading a receipt, order, or
    document from an image - one call per document, every line item
    included ('label', optional 'quantity', 'amount_cents', 'group',
    'note'). Preserve the source's own grouping in 'group' (a shipment
    like "Arriving Thu, Aug 27", a sub-receipt, a page): the groups are
    what map items to the right charge later.
    'fields' is every other visible fact, by its label - the issuer's
    name, address, phone, email, website, dates, totals, tax, account
    or invoice numbers - whether or not this question needs them: a
    later question will, and the image will be gone. A document with no
    line items (a letter, a card) is recorded with 'fields' alone.
    The image itself is gone after this turn; this record is what
    later turns (and you) get instead. Returns the count recorded, or
    an 'error' explaining exactly what to fix."""
    staged = _staged.get()
    if staged is None:
        return Refused(error="No conversation turn is active; nothing was recorded.")
    try:
        reading = Reading(kind=kind, title=title, items=items, fields=fields or {})
    except ValidationError as e:
        return Refused(error=f"invalid reading: {e}")
    staged.append(reading)
    return Recorded(recorded=len(reading.items), title=reading.title)


async def merge_staged_readings(
    user_id: str,
    staged: list[Reading],
    legacy: list[dict[str, Any]] | None = None,
) -> None:
    """Fold the turn's staged readings into the user's store, newest
    kept, bounded so context injection stays affordable.

    ``legacy`` carries readings a conversation recorded back when the
    store was per-conversation: they are folded in on the first write
    for a user who has none, so an in-flight thread keeps what it read
    instead of paying for the cutover. Once anything is stored the
    parameter is ignored and there is one home again.
    """
    if not staged:
        return

    try:
        from app.core.db import get_async_session
        from app.services.ai.domains.chat.user_memory import (
            load_user_readings,
            store_user_readings,
        )
    except ImportError:
        # A memory-backend project ships neither app.core.db nor the
        # per-user memory table. The tool stays registered so the model
        # sees one shape everywhere; a reading just lives for the turn
        # that took it, which is what a memory backend means.
        return

    async with get_async_session() as session:
        readings = await load_user_readings(session, user_id)
        if not readings and legacy:
            readings = kept_readings(legacy)
        readings.extend(staged)
        await store_user_readings(session, user_id, readings[-_MAX_READINGS_PER_USER:])


def format_readings(readings: list[Reading] | None) -> str | None:
    """The context block for stored readings, or None when there are
    none - rendered fresh into every turn so the extraction outlives
    the image it came from."""
    if not readings:
        return None
    lines = [
        "## RECORDED READINGS",
        "Extractions you recorded from images attached earlier - the",
        "images are gone, these records are authoritative:",
    ]
    for reading in readings:
        lines.append(f"\n### {reading.title} ({reading.kind})")
        lines.extend(f"{label}: {value}" for label, value in reading.fields.items())
        current_group: str | None = None
        for item in reading.items:
            group = item.group
            if group and group != current_group:
                lines.append(f"[{group}]")
                current_group = group
            piece = f"- {item.label}"
            if item.quantity > 1:
                piece += f" x{item.quantity}"
            if item.amount_cents is not None:
                piece += f" - ${item.amount_cents / 100:.2f}"
                if item.quantity > 1:
                    piece += " each"
            if item.note:
                piece += f" ({item.note})"
            lines.append(piece)
    return "\n".join(lines)


# Built-in registration: importing this module makes the tool grantable
# via the agent registry. replace=True keeps re-imports idempotent.
register_tool(
    "record_reading",
    record_reading,
    description="Durably record everything read from an attached image",
    effect="writes",
    replace=True,
)
