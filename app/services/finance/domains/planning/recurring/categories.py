"""What category a stream is, read off its members (#171).

Split from ``streams`` at its budget: a derived read, not the row's
lifecycle.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.planning.recurring import queries


async def stream_category_names(
    db: AsyncSession, stream_ids: Sequence[int] | set[int]
) -> dict[int, str]:
    """Each stream's category, derived from its member transactions.

    ``finance_recurring_stream.category_id`` is a provider field the
    local detector never fills, so the stream table itself has no
    category to show. The transactions DO carry one (import maps the
    Quicken category path), and a stream is one merchant's rhythm -
    so the most common category across its members is the stream's
    category. Ties break on the higher count, then category id.
    """
    ids = list(stream_ids)
    if not ids:
        return {}
    rows = await queries.stream_member_category_votes(db, ids)
    best: dict[int, tuple[int, str]] = {}
    for stream_id, name, hits in rows:
        current = best.get(stream_id)
        if current is None or hits > current[0]:
            best[stream_id] = (hits, name)
    resolved = {stream_id: name for stream_id, (_, name) in best.items()}

    # A category set ON THE BILL outranks the inference. Without this
    # the edit saves to a column nothing reads, and Bills & Income
    # keeps showing whatever its transactions vote for - the change
    # looks accepted and does nothing.
    stored = await queries.stream_stored_category_names(db, ids)
    resolved.update({stream_id: name for stream_id, name in stored if name})
    return resolved
