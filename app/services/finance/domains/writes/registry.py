"""Steward's change types, registered on the template's queue (``change_queue``).

Steward's executors predate the queue's shape: ``execute`` answers a dict
of what changed and ``describe`` reads one payload at a time.
``finance_type`` takes one as written and hands the queue its own
``ChangeExecutor``, so there is one queue, one registry and one approval
path. On the way it runs every approval as the proposer's action in the
transaction edit log (#325), a batch's cards as one action, and re-reads
the unfiled documents a fact change may now explain (#409).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import functools
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.change_queue import ChangeDisplayRow, ChangeExecutor, approving

Execute = Callable[[AsyncSession, Any, int | None], Awaitable[dict[str, Any]]]
Describe = Callable[[AsyncSession, Any, int | None], Awaitable[list[ChangeDisplayRow]]]


class Executed(BaseModel):
    """What an approval changed, as the executor said it: kept whole in the
    row's ``result`` (the ids an announcement quotes back)."""

    model_config = ConfigDict(extra="allow")


def finance_type(
    *, change_type: str, execute: Execute, describe: Describe, **options: Any
) -> ChangeExecutor:
    """The queue's ``ChangeExecutor`` for one of Steward's change types;
    ``options`` are the rest of its fields (``title``, ``payload_model``,
    ``editable``...)."""
    return ChangeExecutor(
        change_type=change_type,
        execute=_logged(change_type, execute),
        describe=_each(describe),
        **options,
    )


def _logged(change_type: str, execute: Execute) -> Any:
    @functools.wraps(execute)
    async def run(
        db: AsyncSession, payload: Any, owner_user_id: int | None
    ) -> Executed:
        from app.services.documents.service import filing
        from app.services.finance.domains.ledger import changelog

        row = approving.get()
        actor = (row.proposed_by_agent if row else None) or "you"
        # A batch's cards are one action, undone as one: they share its id.
        with changelog.acting(actor, join=True, batch=row.batch_id if row else None):
            result = await execute(db, payload, owner_user_id)
        if change_type in filing.FACT_CHANGES:
            # What just landed may be what an unfiled document prints.
            await filing.reread_unfiled(db, owner_user_id=owner_user_id)
        return Executed(**result)

    return run


def _each(describe: Describe) -> Any:
    # ponytail: one describe per card, so a queue of N costs N reads of each
    # type; give a type a list-based describe where a long queue is slow.
    @functools.wraps(describe)
    async def run(
        db: AsyncSession, payloads: list[Any], owner_user_id: int | None
    ) -> list[list[ChangeDisplayRow]]:
        return [await describe(db, payload, owner_user_id) for payload in payloads]

    return run
