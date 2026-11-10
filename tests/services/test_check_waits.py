"""A check scan with no row yet waits for it (#423).

A check in a bank's download that matched no ledger row was dropped,
and nothing tried again when the row synced. Its reading is kept on the
document with its scans in storage, so the retry needs no OCR or model
call; each sync, import and nightly sweep matches again and files the
card in the download's batch shape; after the same wait as a receipt it
becomes an Attention item, once.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.domains.reading import checks, checks_waiting, waiting
from app.services.documents.service import DocumentService
from tests._session import opens
from tests.services._finance_factories import pending_cards, seed_charge
from tests.services.test_check_images import OCR_1524, _download
from tests.services.test_finance_insights import _insights_of


async def _download_read(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> int:
    """One check, 1524 for $25.00, read off a download with no row for it."""
    pdf = _download([("white", "gray")])
    document = await DocumentService(db).ingest(
        pdf, title="checkdownload.pdf", media_type="application/pdf"
    )
    monkeypatch.setattr(checks, "ocr", lambda image: OCR_1524)
    made = await checks.propose_checks(opens(db), int(document.id or 0))
    assert made == 0
    return int(document.id or 0)


async def _row(db: AsyncSession, number: str, cents: int, day: date) -> int:
    return await seed_charge(db, cents, day, f"CHECK # {number}")


async def _cards(db: AsyncSession) -> list[Any]:
    return await pending_cards(db, checks.CHECK)


class TestItWaits:
    @pytest.mark.asyncio
    @pytest.mark.queryspy(threshold=4)  # read, looked for, then the row, looked for
    async def test_the_reading_is_kept_and_the_row_arriving_later_gets_the_card(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = async_db_session
        document_id = await _download_read(db, monkeypatch)

        kept = (await DocumentService(db).get(document_id)).meta_data[
            checks_waiting.WAITING
        ]
        assert [(k["number"], k["amount_cents"]) for k in kept] == [("1524", 2500)]
        assert kept[0]["front_key"] and kept[0]["back_key"]
        assert await checks_waiting.retry(db, owner_user_id=None) == 0

        # The row syncs; the retry reads nothing off the scan again.
        row = await _row(db, "1524", -2500, date(2025, 7, 1))
        monkeypatch.setattr(checks, "ocr", lambda image: pytest.fail("read again"))
        assert await checks_waiting.retry(db, owner_user_id=None) == 1

        (card,) = await _cards(db)
        assert card.payload["transaction_id"] == row
        assert card.payload["front_key"] == kept[0]["front_key"]
        assert card.batch_id is not None
        assert (
            checks_waiting.WAITING
            not in (await DocumentService(db).get(document_id)).meta_data
        )

    @pytest.mark.asyncio
    @pytest.mark.queryspy(threshold=3)  # looked for twice
    async def test_after_the_wait_it_asks_once_and_stops(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = async_db_session
        document_id = await _download_read(db, monkeypatch)
        document = await DocumentService(db).get(document_id)
        document.created_at = datetime.now() - timedelta(days=waiting.WAIT_DAYS + 1)
        db.add(document)
        await db.flush()

        assert await checks_waiting.retry(db, owner_user_id=None) == 0
        assert await checks_waiting.retry(db, owner_user_id=None) == 0

        (item,) = await _insights_of(db, checks_waiting.UNMATCHED)
        assert item.title == "No row found for check #1524"
        assert "$25.00" in (item.body or "")
        assert (
            checks_waiting.WAITING
            not in (await DocumentService(db).get(document_id)).meta_data
        )


@pytest.mark.asyncio
async def test_every_arrival_looks_for_checks_too(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.documents.domains.reading import receipts

    looked: list[str] = []

    async def _receipts(db: Any, *, owner_user_id: Any) -> int:
        looked.append("receipts")
        return 1

    async def _checks(db: Any, *, owner_user_id: Any) -> int:
        looked.append("checks")
        return 2

    monkeypatch.setattr(receipts, "match_waiting", _receipts)
    monkeypatch.setattr(checks_waiting, "retry", _checks)
    assert await waiting.look_again(async_db_session, owner_user_id=None) == 3
    assert looked == ["receipts", "checks"]
