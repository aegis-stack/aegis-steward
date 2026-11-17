"""The ids a finance proposal names, for agents.

The write tools themselves are the queue's (``change_queue.tools``:
propose, propose_many, pending, withdraw, withdraw_batch, revise); these
are the lookups a payload needs: ``categories`` for a categorize's
``category_id``, ``tags`` for a tag's name.
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_async_session
from app.core.tools import register_tool


async def categories() -> dict[str, Any]:
    """Every assignable category: 'id', 'name' and 'classification'
    ('expense' | 'income' | 'transfer'). The id is what a
    transaction.categorize proposal's 'category_id' takes.
    """
    from sqlmodel import select

    from app.services.finance.models import FinanceCategory

    async with get_async_session() as session:
        rows = (
            await session.exec(
                select(FinanceCategory)
                .where(FinanceCategory.is_archived == False)  # noqa: E712
                .order_by(FinanceCategory.name)
            )
        ).all()
    return {
        "categories": [
            {"id": row.id, "name": row.name, "classification": row.classification}
            for row in rows
        ]
    }


async def tags() -> dict[str, Any]:
    """Every live tag with how many transactions wear it: 'id', 'name',
    'count'. Tags are the label axis ORTHOGONAL to categories (a
    "Business" tag on a Software-categorized row). A transaction.tag
    payload takes the NAME - reuse an existing spelling from here before
    coining a new one."""
    from app.services.finance.domains.ledger.transactions import list_tags

    async with get_async_session() as session:
        rows = await list_tags(session, owner_user_id=None)
    return {"tags": [{"id": t.id, "name": t.name, "count": count} for t, count in rows]}


# Built-in registration: importing this module makes the tools grantable
# via the agent registry. replace=True keeps re-imports idempotent.
register_tool(
    "categories",
    categories,
    description="Assignable categories with the ids proposals need",
    effect="read",
    replace=True,
)
register_tool(
    "tags",
    tags,
    description="The tag directory: names, ids and usage counts",
    effect="read",
    replace=True,
)
