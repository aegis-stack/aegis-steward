"""Receipts leave with their transactions (#332).

The register's filtered rows export as one packet: the rows as a CSV,
each row's receipts as files beside it, and for an HSA, the claim each
charge paid with its EOB. Bulk export of receipts is the top ask on
Monarch's receipt scanning, for HSA records and to avoid lock-in.
"""

from __future__ import annotations

import csv
from datetime import date
import io
import zipfile

from fastapi.testclient import TestClient
import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.service import DocumentService
from app.services.finance.constants import transaction_tag
from app.services.finance.models import FinanceTransaction
from app.services.insurance.service import InsuranceService
from app.services.matters.service import PartyService
from tests.web.conftest import Ledger
from tests.web.dom import one

EXPORT = "/transactions/export"


async def _gas(db: AsyncSession) -> int:
    row = (
        await db.exec(
            select(FinanceTransaction).where(FinanceTransaction.name == "Gas")
        )
    ).one()
    return int(row.id or 0)


async def _with_receipt_and_claim(db: AsyncSession, gas: int) -> tuple[int, int]:
    documents = DocumentService(db)
    receipt = await documents.ingest(
        b"%PDF-1.4 gas receipt", title="Gas receipt", media_type="application/pdf"
    )
    await documents.tag(int(receipt.id or 0), transaction_tag(gas))
    eob = await documents.ingest(
        b"%PDF-1.4 eob", title="EOB", media_type="application/pdf", kind="statement"
    )
    parties = PartyService(db)
    insurer = await parties.create(name="Delta Dental", kind="organization")
    patient = await parties.create(name="Sam Doe", kind="person")
    insurance = InsuranceService(db)
    policy = await insurance.create_policy(
        insurer_party_id=int(insurer.id or 0),
        covered_party_ids=[int(patient.id or 0)],
        kind="dental",
    )
    claim = await insurance.record_claim(
        policy_id=int(policy.id or 0),
        covered_party_id=int(patient.id or 0),
        service_on=date(2026, 9, 3),
        claim_number="C-77",
        patient_owes_cents=2000,
        document_id=int(eob.id or 0),
    )
    await insurance.mark_paid(int(claim.id or 0), gas, owner_user_id=None)
    await db.commit()
    return int(receipt.id or 0), int(eob.id or 0)


class TestThePacket:
    @pytest.mark.asyncio
    async def test_the_filtered_rows_leave_with_their_receipts_and_claims(
        self, client: TestClient, ledger: Ledger, async_db_session: AsyncSession
    ) -> None:
        gas = await _gas(async_db_session)
        await _with_receipt_and_claim(async_db_session, gas)

        answer = client.get(EXPORT, params={"q": "Gas"})

        assert answer.status_code == 200
        assert answer.headers["content-type"] == "application/zip"
        assert (
            'attachment; filename="transactions'
            in answer.headers["content-disposition"]
        )
        packet = zipfile.ZipFile(io.BytesIO(answer.content))
        names = sorted(packet.namelist())
        assert names == [
            "claims.csv",
            f"eobs/{gas}-EOB.pdf",
            f"receipts/{gas}-Gas receipt.pdf",
            "transactions.csv",
        ]
        (row,) = list(
            csv.DictReader(io.StringIO(packet.read("transactions.csv").decode()))
        )
        assert row["payee"] == "Gas" and row["amount"] == "-20.00"
        assert row["category"] == "Auto:Fuel" and row["account"] == "Visa"
        assert row["receipts"] == f"receipts/{gas}-Gas receipt.pdf"
        assert row["claim"] == "C-77"
        (claim,) = list(csv.DictReader(io.StringIO(packet.read("claims.csv").decode())))
        assert claim["claim"] == "C-77" and claim["patient_owes"] == "20.00"
        assert (
            claim["transaction_id"] == str(gas)
            and claim["eob"] == f"eobs/{gas}-EOB.pdf"
        )
        assert packet.read(f"receipts/{gas}-Gas receipt.pdf") == b"%PDF-1.4 gas receipt"

    def test_rows_without_paper_still_export(
        self, client: TestClient, ledger: Ledger
    ) -> None:
        answer = client.get(EXPORT, params={"q": "Market"})

        packet = zipfile.ZipFile(io.BytesIO(answer.content))
        assert packet.namelist() == ["transactions.csv"]
        rows = list(
            csv.DictReader(io.StringIO(packet.read("transactions.csv").decode()))
        )
        assert [r["amount"] for r in rows] == ["-30.00", "-15.00"]
        assert all(r["receipts"] == "" and r["claim"] == "" for r in rows)

    def test_the_register_offers_the_export_with_its_filters(
        self, client: TestClient, ledger: Ledger
    ) -> None:
        link = one(client.get("/accounts/all?q=Gas").text, "a[data-export]")
        assert link.get("href") == f"{EXPORT}?q=Gas"

    def test_an_account_page_offers_its_own_export(
        self, client: TestClient, ledger: Ledger
    ) -> None:
        card = one(client.get(f"/accounts/{ledger.card}").text, "a[data-export]")
        assert card.get("href") == f"{EXPORT}?account_id={ledger.card}"


class TestScope:
    def test_an_account_page_exports_only_its_rows(
        self, client: TestClient, ledger: Ledger
    ) -> None:
        answer = client.get(EXPORT, params={"account_id": ledger.card})
        packet = zipfile.ZipFile(io.BytesIO(answer.content))
        rows = list(
            csv.DictReader(io.StringIO(packet.read("transactions.csv").decode()))
        )
        assert sorted(r["payee"] for r in rows) == ["Gas", "Mystery charge"]
