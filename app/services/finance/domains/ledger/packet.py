"""Receipts leave with their transactions (#332).

A filtered register, as one zip: the rows as ``transactions.csv``, each
row's receipts as files under ``receipts/``, and for the HSA packet the
claim each charge paid (``claims.csv``) with its EOB under ``eobs/``.
Bulk export is the top ask on Monarch's receipt scanning: for HSA
records, for taxes, and so the paper is never locked in.
"""

from __future__ import annotations

import csv
import io
import mimetypes
from typing import Any
import zipfile

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.formatting import safe_filename
from app.core.money import plain_dollars
from app.services.finance.schemas import TransactionResponse

ROWS = "transactions.csv"
CLAIMS = "claims.csv"
RECEIPTS = "receipts"
EOBS = "eobs"


def _file(folder: str, transaction_id: int, document: Any) -> str:
    """``receipts/12-Gas receipt.pdf``: the row it belongs to first, so a
    folder of them sorts with the CSV."""
    extension = mimetypes.guess_extension(document.media_type or "") or ""
    return f"{folder}/{transaction_id}-{safe_filename(document.title)}{extension}"


async def receipts_packet(
    db: AsyncSession, items: list[TransactionResponse], *, owner_user_id: int | None
) -> bytes:
    from app.core.storage import get_storage
    from app.services.documents.service import documents_by_ids, tagged_with
    from app.services.finance.constants import transaction_tag
    from app.services.finance.domains.ledger.queries.accounts import account_names
    from app.services.insurance.service import InsuranceService

    ids = [t.id for t in items]
    names = await account_names(db, [t.account_id for t in items])
    filed = await tagged_with(db, [transaction_tag(i) for i in ids])
    claims = await InsuranceService(db).claims_paid_by(ids)
    documents = await documents_by_ids(
        db,
        [d for ids_ in filed.values() for d in ids_]
        + [c.document_id for c in claims if c.document_id],
        owner_user_id=owner_user_id,
    )
    storage = get_storage()
    # Each stored file once, however many rows or claims it serves.
    stored = {
        key: await storage.get(key)
        for key in {d.storage_key for d in documents.values()}
    }

    receipt_files: dict[int, list[str]] = {}
    eob_files: dict[int, str] = {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as packet:
        for txn in items:
            for doc_id in filed.get(transaction_tag(txn.id), []):
                if (doc := documents.get(doc_id)) is not None:
                    name = _file(RECEIPTS, txn.id, doc)
                    packet.writestr(name, stored[doc.storage_key])
                    receipt_files.setdefault(txn.id, []).append(name)
        for claim in claims:
            doc = documents.get(claim.document_id or 0)
            if doc is not None and claim.paid_transaction_id:
                name = _file(EOBS, claim.paid_transaction_id, doc)
                packet.writestr(name, stored[doc.storage_key])
                eob_files[int(claim.id or 0)] = name
        by_txn = {int(c.paid_transaction_id or 0): c for c in claims}
        rows = io.StringIO()
        out = csv.writer(rows)
        out.writerow(
            ["date", "payee", "amount", "category", "account", "receipts", "claim"]
        )
        for txn in items:
            claim = by_txn.get(txn.id)
            out.writerow(
                [
                    txn.date.isoformat(),
                    txn.payee,
                    plain_dollars(txn.amount),
                    txn.category or "",
                    names.get(txn.account_id, ""),
                    "; ".join(receipt_files.get(txn.id, [])),
                    (claim.claim_number or "") if claim else "",
                ]
            )
        packet.writestr(ROWS, rows.getvalue())
        if claims:
            rows = io.StringIO()
            out = csv.writer(rows)
            out.writerow(
                ["claim", "service_on", "patient_owes", "transaction_id", "eob"]
            )
            for claim in claims:
                out.writerow(
                    [
                        claim.claim_number or "",
                        claim.service_on.isoformat(),
                        plain_dollars(claim.patient_owes_cents),
                        claim.paid_transaction_id or "",
                        eob_files.get(int(claim.id or 0), ""),
                    ]
                )
            packet.writestr(CLAIMS, rows.getvalue())
    return buffer.getvalue()
