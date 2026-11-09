"""A receipt is attached to its transaction, from the register (#331).

The row's menu opens a dialog that takes a PDF or a photo; it lands on
the shelf like any upload (``documents.file_upload``), filed on the
transaction by ``transaction_tag``, and the row comes back wearing the
paperclip that opens it. Its own module because ``transactions`` is at
its budget.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.responses import Response

from app.components.web_frontend.documents import file_upload
from app.components.web_frontend.rendering import close_dialog, dialog, with_toast
from app.components.web_frontend.routes.finance.register import (
    RegisterFilters,
    listing_for,
    register_filters,
)
from app.components.web_frontend.routes.finance.transactions import (
    _txns,
    rows_response,
)
from app.components.web_frontend.routes.requests import ACCEPTS
from app.services.finance.constants import transaction_tag
from app.services.finance.deps import get_finance_service, get_owner_user_id
from app.services.finance.service import FinanceService, receipts_packet

router = APIRouter(prefix="/transactions")

# How many rows leave in one packet: a year of a busy household, not a
# page. ponytail: one zip in memory; stream it if a packet ever outgrows this.
PACKET_ROWS = 5000


@router.get("/export", include_in_schema=False)
async def export_packet(
    filters: Annotated[RegisterFilters, Depends(register_filters)],
    service: Annotated[FinanceService, Depends(get_finance_service)],
    owner_user_id: Annotated[int | None, Depends(get_owner_user_id)],
    account_id: int | None = None,
) -> Response:
    """The register's filtered rows, with their receipts and claims, as
    one zip (#332): the same listing the page shows."""
    listing = await listing_for(
        filters, account_id, service, owner_user_id, page_size=PACKET_ROWS
    )
    packet = await receipts_packet(
        service.db, listing.items, owner_user_id=owner_user_id
    )
    return Response(
        packet,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="transactions-with-receipts.zip"'
        },
    )


def _form(
    request: Request,
    transaction_id: int,
    show_account: bool,
    errors: list[str] | None = None,
) -> Response:
    return dialog(
        request,
        "partials/transactions/receipt.html",
        422 if errors else 200,
        post=f"/transactions/{transaction_id}/receipt",
        accepts=ACCEPTS,
        show_account=show_account,
        errors=errors or [],
    )


@router.get("/{transaction_id:int}/receipt", include_in_schema=False)
async def receipt_form(
    request: Request,
    transaction_id: int,
    show_account: bool = False,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    await _txns(service, [transaction_id], owner_user_id)
    return _form(request, transaction_id, show_account)


@router.post("/{transaction_id:int}/receipt", include_in_schema=False)
async def attach_receipt(
    request: Request,
    transaction_id: int,
    file: Annotated[UploadFile | None, File()] = None,
    show_account: Annotated[bool, Form()] = False,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """File the receipt on its transaction; the row comes back with it."""
    txns = await _txns(service, [transaction_id], owner_user_id)
    try:
        document = await file_upload(
            service.db,
            file,
            owner_user_id=owner_user_id,
            tags=(transaction_tag(transaction_id),),
            kind="receipt",
        )
    except HTTPException as exc:
        return _form(request, transaction_id, show_account, [str(exc.detail)])
    await service.db.commit()
    response = await rows_response(request, service, txns, owner_user_id, show_account)
    return close_dialog(with_toast(response, f"Receipt attached: {document.title}"))
