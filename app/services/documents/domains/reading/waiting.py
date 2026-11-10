"""Paper that waits for its ledger row, looked for again.

A receipt waits for its charge (#330) and a check scan for its row
(#423); every sync, import and nightly sweep gives each another look.
One door, so a new kind of waiting paper is looked for everywhere the
old kind is, and no arrival path is missed. The wait is one wait, and
what happens when it runs out - an Attention item, once - is one rule.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

# How long paper waits for its row before it asks for a person, and
# how long after that the nightly sweep has to ask: paper older than
# both - kept on the shelf before anything waited - is not waiting for
# anything, and is never read again.
WAIT_DAYS = 30
ASKING_DAYS = 7
WHAT_TO_DO = "Attach it from its transaction's menu, or dismiss this."


async def look_again(db: AsyncSession, *, owner_user_id: int | None) -> int:
    """Every kind of waiting paper, looked for once more; how many
    cards that made."""
    from app.services.documents.domains.reading import checks_waiting, receipts

    made = await receipts.match_waiting(db, owner_user_id=owner_user_id)
    return made + await checks_waiting.retry(db, owner_user_id=owner_user_id)


async def flag_once(
    db: AsyncSession,
    owner_user_id: int | None,
    insight_type: str,
    items: list[tuple[str, str, str, int | None]],
) -> None:
    """Paper nothing matched in ``WAIT_DAYS``: an Attention item for
    each, once (the key dedups it), saying what it is and what to do
    with it. ``items`` are (what makes the key, title, what happened,
    amount); what to do about it is one sentence, said here."""
    from app.services.finance.service import create_insight_if_new
    from app.services.shared.queries import stored_owner

    for key, title, body, amount in items:
        await create_insight_if_new(
            db,
            owner_user_id=stored_owner(owner_user_id),
            insight_type=insight_type,
            dedup_key=f"{insight_type}:{key}",
            severity="info",
            title=title,
            body=f"{body} {WHAT_TO_DO}",
            detected_amount=amount,
        )
