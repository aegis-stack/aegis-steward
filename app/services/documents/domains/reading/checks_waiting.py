"""A check scan with no row yet waits for it (#423).

``propose_checks`` makes a card only for a scan that matches a ledger
row when the download is read; a check whose row has not synced yet
was dropped, and nothing tried again. Its reading - number, amount,
date, payee, the account off its MICR line - is kept on the document
with its scans already in storage, so a retry costs no OCR or model
call. Each sync, import and nightly sweep matches it again and files
the card in the download's batch shape; after ``WAIT_DAYS`` it becomes
an Attention item, once, and is let go.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.domains.reading.waiting import (
    ASKING_DAYS,
    WAIT_DAYS,
    flag_once,
)

# Where a document keeps the scans still waiting for their rows.
WAITING = "waiting_checks"
UNMATCHED = "check_unmatched"


async def remember(
    db: AsyncSession, document_id: int, scans: list[dict[str, Any]]
) -> None:
    """Keep these unmatched readings on the document, beside any kept
    already; the same slot is kept once."""
    from app.services.documents.models import Document

    if not scans:
        return
    document = await db.get(Document, document_id)
    if document is None:
        return
    kept = list(document.meta_data.get(WAITING) or [])
    slots = {(k["page"], k["slot"]) for k in kept}
    kept += [s for s in scans if (s["page"], s["slot"]) not in slots]
    document.meta_data = {**document.meta_data, WAITING: kept}
    db.add(document)
    await db.flush()


async def retry(
    db: AsyncSession, *, owner_user_id: int | None, today: date | None = None
) -> int:
    """Match every waiting scan against the ledger again, one card per
    row found as one batch per download; put the ones done waiting in
    front of a person. Returns how many cards were made."""
    from app.services.documents.domains.reading.checks import (
        CHECK,
        PROPOSED_BY,
        card_for,
        match,
        renamed_rows,
        the_ledger,
    )
    from app.services.finance.service import propose_many
    from app.services.finance.utils import current_date

    today = today or current_date()
    holding = await _holding(db, owner_user_id, today)
    if not holding:
        return 0
    fresh = {
        d.id: d for d in holding if (today - d.created_at.date()).days <= WAIT_DAYS
    }
    await _done_waiting(db, [d for d in holding if d.id not in fresh], owner_user_id)
    if not fresh:
        return 0
    rows, done, payees = await the_ledger(db, set(fresh), owner_user_id)
    found = [
        (d, scan, reading, match(reading, rows))
        for d in fresh.values()
        for scan in d.meta_data.get(WAITING) or []
        if (d.id, scan["page"], scan["slot"]) not in done.slots
        for reading in (_reading(scan),)
    ]
    lost = [r for _, _, r, row in found if row is None and r.account and r.dated]
    if lost:
        renamed = await renamed_rows(db, lost, owner_user_id)
        found = [
            (d, scan, r, row or match(r, [], renamed)) for d, scan, r, row in found
        ]
    made = 0
    claimed: set[int] = set()
    for document in fresh.values():
        cards = []
        matched: set[tuple[int, int]] = set()
        for d, scan, reading, row in found:
            if d.id != document.id or row is None:
                continue
            if row.id in done.transactions or row.id in claimed:
                continue
            claimed.add(row.id)
            matched.add((scan["page"], scan["slot"]))
            cards.append(
                card_for(
                    int(document.id or 0),
                    scan["page"],
                    scan["slot"],
                    row,
                    reading,
                    payees,
                    front_key=scan["front_key"],
                    back_key=scan.get("back_key"),
                )
            )
        if cards:
            await propose_many(
                db,
                CHECK,
                cards,
                owner_user_id=owner_user_id,
                proposed_by_agent=PROPOSED_BY,
            )
            made += len(cards)
            _let_go(document, matched)
            db.add(document)
    await db.flush()
    return made


def _reading(scan: dict[str, Any]) -> Any:
    from app.services.documents.domains.reading.checks import CheckReading

    fields = {k: scan.get(k) for k in CheckReading.__dataclass_fields__}
    fields["dated"] = date.fromisoformat(fields["dated"]) if fields["dated"] else None
    return CheckReading(**fields)


def _let_go(document: Any, slots: set[tuple[int, int]] | None) -> None:
    """Drop these scans (all of them, for None) from what waits."""
    kept = [
        k
        for k in document.meta_data.get(WAITING) or []
        if slots is not None and (k["page"], k["slot"]) not in slots
    ]
    meta = {k: v for k, v in document.meta_data.items() if k != WAITING}
    document.meta_data = {**meta, WAITING: kept} if kept else meta


async def _holding(
    db: AsyncSession, owner_user_id: int | None, today: date
) -> list[Any]:
    """Live documents young enough to be waiting that hold a scan still
    waiting. One read; the scans are on the row."""
    from app.services.documents.queries import documents_holding

    since = today - timedelta(days=WAIT_DAYS + ASKING_DAYS)
    return await documents_holding(
        db, WAITING, owner_user_id=owner_user_id, since=since
    )


async def _done_waiting(
    db: AsyncSession, done: list[Any], owner_user_id: int | None
) -> None:
    """A scan nothing matched in ``WAIT_DAYS``: an Attention item, once,
    and the document stops holding it."""
    from app.core.money import format_money

    items = []
    for document in done:
        for scan in document.meta_data.get(WAITING) or []:
            number = scan.get("number") or "?"
            amount = scan.get("amount_cents")
            said = format_money(amount) if amount else "an unread amount"
            on = f", dated {scan['dated']}" if scan.get("dated") else ""
            items.append(
                (
                    f"{document.id}:{scan['page']}:{scan['slot']}",
                    f"No row found for check #{number}",
                    f"{said}{on}, in {document.title}, waited {WAIT_DAYS} days.",
                    amount,
                )
            )
        _let_go(document, None)
        db.add(document)
    await flag_once(db, owner_user_id, UNMATCHED, items)
