"""Who is related to whom (#289).

"What children do you have under this household" had no answer: people
were contacts and nothing more. Two people are related as spouses, as
parent and child, or otherwise; one row says it, and it reads from both
sides - the child's view of a "parent" row is "child of".
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlmodel import col, delete, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.matters.models import PartyRelation
from app.services.matters.schemas import Relation

# The kinds, and how each reads from its two ends.
RELATIONS: dict[str, tuple[str, str]] = {
    "spouse": ("spouse of", "spouse of"),
    "parent": ("parent of", "child of"),
    "other": ("related to", "related to"),
}


async def relate(
    db: AsyncSession, party_id: int, related_party_id: int, relation: str
) -> bool:
    """Record it; False when it already is."""
    existing = (
        await db.exec(
            select(PartyRelation.id).where(
                PartyRelation.party_id == party_id,
                PartyRelation.related_party_id == related_party_id,
                PartyRelation.relation == relation,
            )
        )
    ).first()
    if existing is not None:
        return False
    db.add(
        PartyRelation(
            party_id=party_id, related_party_id=related_party_id, relation=relation
        )
    )
    await db.flush()
    return True


async def unrelate(
    db: AsyncSession, party_id: int, related_party_id: int, relation: str
) -> None:
    await db.exec(
        delete(PartyRelation).where(
            col(PartyRelation.party_id) == party_id,
            col(PartyRelation.related_party_id) == related_party_id,
            col(PartyRelation.relation) == relation,
        )
    )
    await db.flush()


async def relations_for(
    db: AsyncSession, party_ids: Iterable[int]
) -> dict[int, list[Relation]]:
    """Each party's relationships, read from its own side: ``relation``
    ("parent of", "child of", ...), the other ``party_id`` and its name
    (``party``). Two queries, however many parties."""
    from app.services.matters.service import PartyService

    wanted = list(dict.fromkeys(party_ids))
    found: dict[int, list[Relation]] = {party: [] for party in wanted}
    if not wanted:
        return found
    rows = await db.exec(
        select(PartyRelation).where(
            or_(
                col(PartyRelation.party_id).in_(wanted),
                col(PartyRelation.related_party_id).in_(wanted),
            )
        )
    )
    for row in rows.all():
        forward, backward = RELATIONS.get(row.relation, RELATIONS["other"])
        if row.party_id in found:
            found[row.party_id].append(
                {"relation": forward, "party_id": row.related_party_id, "party": None}
            )
        if row.related_party_id in found:
            found[row.related_party_id].append(
                {"relation": backward, "party_id": row.party_id, "party": None}
            )
    linked = [r for related in found.values() for r in related]
    names = await PartyService(db).names([r["party_id"] for r in linked])
    for r in linked:
        r["party"] = names.get(r["party_id"])
    return found
