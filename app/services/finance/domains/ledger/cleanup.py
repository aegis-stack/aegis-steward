"""The read behind "clean up" (#597): what the ledger already knows about
each row nobody filed.

Asked to tidy, an agent used to read a window of rows and guess. The
evidence was there all along - the payee's own precedent (the Review
page's sweep) and the overdue bill the matcher ranks a payment for -
in two reads it was never told to combine. This is the one read.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.db import get_async_session
from app.core.tools import register_tool
from app.services.finance.schemas.agent_tools import Cleanup, CleanupRow

DEFAULT_DAYS = 30


async def cleanup_candidates(days: int = DEFAULT_DAYS) -> Cleanup:
    """Every uncategorized transaction of the last ``days`` that no pending
    card already speaks for, newest first, each with the best evidence the ledger holds for it: 'evidence' is
    'precedent' (this payee's own filed rows agree on
    'suggested_category'), 'bill' (an overdue bill it is named for ranks it as a
    payment: 'candidate_bill_id' and 'bill_name', with the bill's usual
    category suggested), or null (nothing speaks to it: ask).

    Propose from it, never beyond it: a 'precedent' row is a
    transaction.categorize with 'suggested_category_id'; a 'bill' row is
    a recurring.match with 'candidate_bill_id' as the stream_id (the
    match files the category too). Batch alike rows in one
    propose_many. Rows with no evidence are a list to put to the user,
    not a guess.
    """
    from app.services.finance.domains.planning.recurring.categories import (
        stream_category_names,
    )
    from app.services.finance.domains.planning.recurring.matching import named_for
    from app.services.finance.domains.planning.recurring.review import review_queue
    from app.services.finance.service import FinanceService
    from app.services.finance.tools import transaction_rows
    from app.services.finance.utils import current_date

    since = current_date() - timedelta(days=days)
    async with get_async_session() as session:
        service = FinanceService(session)
        rows, _ = await service.uncategorized_transactions(
            owner_user_id=None, limit=None, from_date=since
        )
        # A row already on a pending card is spoken for: "clean up"
        # twice filed every card twice (live, 2026-11-07).
        waiting = {
            change.payload.get("transaction_id")
            for change in await service.list_pending_changes(owner_user_id=None)
        }
        rows = [t for t in rows if t.id not in waiting]
        total = len(rows)
        suggested = {
            s.transaction_id: (s.category_id, s.category_name)
            for s in (
                await service.suggest_categories(
                    owner_user_id=None,
                    transaction_ids=[t.id for t in rows if t.id is not None],
                )
            ).items
        }
        bill_of: dict[int, Any] = {}
        for stream, candidates in await review_queue(service, None):
            for candidate in candidates:
                if candidate.id is not None and named_for(stream.name, None, candidate):
                    bill_of.setdefault(candidate.id, stream)
        bill_categories = await stream_category_names(
            session, {int(s.id or 0) for s in bill_of.values()}
        )
        payees = await service.merchant_names(
            {t.merchant_id for t in rows if t.merchant_id is not None}
        )
        shaped = await transaction_rows(
            session, [(t, payees.get(t.merchant_id)) for t in rows]
        )
    found: list[CleanupRow] = []
    for row in shaped:
        bill = bill_of.get(row["id"])
        category_id, category = suggested.get(row["id"], (None, None))
        if bill is not None:
            evidence = "bill"
            category = bill_categories.get(int(bill.id or 0))
        elif category_id is not None:
            evidence = "precedent"
        else:
            evidence = None
        found.append(
            {
                **row,
                "evidence": evidence,
                "suggested_category": category,
                "suggested_category_id": category_id
                if evidence == "precedent"
                else None,
                "candidate_bill_id": int(bill.id or 0) if bill is not None else None,
                "bill_name": bill.name if bill is not None else None,
            }
        )
    return {"days": days, "total": total, "uncategorized": found}


register_tool(
    "cleanup_candidates",
    cleanup_candidates,
    description="Uncategorized rows of the last N days with the ledger's evidence for each",
    effect="read",
    replace=True,
)
