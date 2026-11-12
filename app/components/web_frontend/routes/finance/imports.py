"""File import: a review, then the import, each a job followed over SSE.

One persistent multipart form in the dialog holds the file; Preview and
Import post it to their own routes and swap ``#import-result``. Both run
as the API's own background job (``imports_job``), so the file is never
parsed in this process (#487); the follower element streams the job's
rendered frames from ``/jobs/{id}/events``, and the last frame is the
review or the summary (``partials/jobs/status.html``).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.responses import Response

from app.components.backend.api.finance.accounts import list_accounts
from app.components.backend.api.finance.base import read_upload
from app.components.backend.api.finance.imports import keep_answers, start_files_job
from app.components.web_frontend.nav import section
from app.components.web_frontend.rendering import (
    dialog,
    dialog_done,
    or_404,
    templates,
    where_from,
)
from app.services.finance.constants import PREVIEW_DETAIL_CAP
from app.services.finance.deps import get_finance_service, get_owner_user_id
from app.services.finance.schemas import LayoutAsk
from app.services.finance.service import (
    DATE_FORMATS,
    FIELDS,
    UPLOADS,
    FinanceService,
    LayoutError,
    can_undo,
    files_in,
    files_label,
    formats_label,
    header_preview,
    imports_job,
    offered,
    run_title,
)

SECTION = section("accounts")
router = APIRouter(prefix=SECTION.path + "/import")

LANES = (
    ("statement", f"Bank or card statement ({formats_label()})"),
    ("investments", "Investment activity (Optum)"),
)


def _lands(by_account: dict[str, int]) -> list[dict[str, Any]]:
    """Per-account new rows, as the house ranked card's rows. One bar is
    not a ranking, it is "To add" restated, so one account gets none."""
    if len(by_account) < 2:
        return []
    ranked = sorted(by_account.items(), key=lambda item: -item[1])
    top = ranked[0][1] or 1
    return [
        {"label": name, "value": f"{count:,}", "ratio": count / top}
        for name, count in ranked
    ]


# The review is rendered by the job's frame, away from any route, so what
# it needs from here is published to the templates.
templates.env.filters["import_lands"] = _lands
templates.env.globals["import_review"] = {
    "cap": PREVIEW_DETAIL_CAP,
    "run_path": router.prefix,
}
templates.env.globals["import_frame"] = imports_job.frame
templates.env.globals["import_layout"] = {
    "fields": FIELDS,
    "date_formats": DATE_FORMATS,
    "path": router.prefix + "/layout",
}


def _fragment(
    request: Request, name: str, status_code: int = 200, **context: Any
) -> Response:
    return templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code
    )


def _error(request: Request, detail: str, status_code: int = 422) -> Response:
    return _fragment(
        request, "partials/imports/error.html", status_code, errors=[detail]
    )


@router.get("", include_in_schema=False)
async def form(
    request: Request,
    account_id: int | None = None,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    listing = await list_accounts(
        include_hidden=False,
        page=1,
        page_size=200,
        service=service,
        owner_user_id=owner_user_id,
    )
    return _fragment(
        request,
        "partials/imports/form.html",
        accounts=listing.items,
        account_id=account_id,
        lanes=LANES,
        accept=",".join(f".{kind}" for kind in UPLOADS),
        formats=formats_label(),
    )


async def _follow(
    request: Request,
    files: list[UploadFile],
    account_id: str,
    kind: str,
    service: FinanceService,
    owner_user_id: int | None,
) -> Response:
    """Store the upload and answer with the follower (pattern 5). Only
    the cheap checks - size, an account you own - happen here. Several
    files are one review (#618); an investment ledger is one file."""
    if kind.startswith("investments") and len(files) > 1:
        return _error(request, "Import one investment file at a time.")
    try:
        job_id = await start_files_job(
            files,
            account_id=int(account_id) if account_id else None,
            kind=kind,
            service=service,
            owner_user_id=owner_user_id,
        )
    except HTTPException as exc:
        return _error(request, str(exc.detail))
    name = files[0].filename if len(files) == 1 else files_label(len(files))
    return _fragment(
        request, "partials/imports/started.html", job_id=job_id, file_name=name
    )


@router.post("/preview", include_in_schema=False)
async def preview(
    request: Request,
    file: Annotated[list[UploadFile], File()],
    account_id: Annotated[str, Form()] = "",
    lane: Annotated[str, Form()] = "statement",
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """A dry run: what a commit would do, from the same plan it executes."""
    kind = "investments-preview" if lane == "investments" else "preview"
    return await _follow(request, file, account_id, kind, service, owner_user_id)


@router.post("", include_in_schema=False)
async def run(
    request: Request,
    file: Annotated[list[UploadFile], File()],
    account_id: Annotated[str, Form()] = "",
    lane: Annotated[str, Form()] = "statement",
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """Start the import. A ledger needs its account before it is stored:
    the job could only fail without one. The review's account answers
    (#620) are kept first, so the job's plan routes by them."""
    if lane == "investments" and not account_id:
        return _error(request, imports_job.NEEDS_ACCOUNT)
    form = await request.form()
    try:
        await keep_answers(
            [str(key) for key in form.getlist("answer_key")],
            [str(choice) for choice in form.getlist("answer_account")],
            service=service,
            owner_user_id=owner_user_id,
        )
    except HTTPException as exc:
        return _error(request, str(exc.detail))
    kind = "investments" if lane == "investments" else "import"
    return await _follow(request, file, account_id, kind, service, owner_user_id)


@router.post("/layout", include_in_schema=False)
async def save_layout(
    request: Request,
    file: Annotated[list[UploadFile], File()],
    account_id: Annotated[str, Form()] = "",
    layout_name: Annotated[str, Form()] = "",
    date_format: Annotated[str, Form()] = "",
    spending_positive: Annotated[str, Form()] = "",
    layout_file: Annotated[str, Form()] = "",
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """An unknown CSV layout, mapped once and kept (#619); then the
    review, as if the file had been known all along. Of several files,
    the one the form was for (#618)."""
    form = await request.form()
    columns = {key: str(form.get(f"col_{key}") or "") for key, _ in FIELDS}
    try:
        named = [
            entry
            for f in file
            for entry in files_in(await read_upload(f), str(f.filename))[0]
        ]
    except (HTTPException, ValueError) as exc:
        return _error(request, str(getattr(exc, "detail", exc)))
    mapped_name, data = next((e for e in named if e[0] == layout_file), named[0])
    try:
        await service.save_layout(
            owner_user_id=owner_user_id,
            file_bytes=data,
            name=layout_name,
            columns=columns,
            date_format=date_format,
            spending_positive=bool(spending_positive),
        )
    except LayoutError as exc:
        ask = LayoutAsk(
            columns=header_preview(data),
            file_name=mapped_name,
            name=layout_name,
            picked=columns,
            date_formats=offered([str(f) for f in form.getlist("offered_format")]),
            reason=str(form.get("reason") or "") or None,
        )
        layout = ask.model_dump() | {
            "date_format": date_format,
            "spending_positive": bool(spending_positive),
            "errors": [str(exc)],
        }
        return _fragment(request, "partials/imports/layout.html", 422, layout=layout)
    await service.db.commit()
    for upload in file:
        await upload.seek(0)
    return await _follow(request, file, account_id, "preview", service, owner_user_id)


def undo_path(batch_id: int) -> str:
    """Where one import is undone: the done screen and the run's dialog
    both open it."""
    return f"{router.prefix}/{batch_id}/undo"


templates.env.globals["import_undo_path"] = undo_path


def _took_back(title: str, done: Any) -> str:
    said = [f"removed {done.removed:,} rows"]
    if done.restored:
        said.append(f"put back {done.restored:,} changes")
    if done.kept:
        said.append(f"kept {done.kept:,} you have edited since")
    return f"Undid {title}: " + ", ".join(said) + "."


async def _undoable(
    service: FinanceService, batch_id: int, owner_user_id: int | None
) -> Any:
    batch = await service.get_import_batch(batch_id, owner_user_id=owner_user_id)
    return or_404(batch if can_undo(batch) else None)


@router.get("/{batch_id:int}/undo", include_in_schema=False)
async def undo_confirm(
    request: Request,
    batch_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    batch = await _undoable(service, batch_id, owner_user_id)
    return dialog(
        request,
        "partials/imports/undo.html",
        title=run_title(batch),
        url=undo_path(batch_id),
    )


@router.post("/{batch_id:int}/undo", include_in_schema=False)
async def undo(
    request: Request,
    batch_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """Take one file back (#621): what it added goes, what it changed
    goes back, and a row edited since stays."""
    batch = await _undoable(service, batch_id, owner_user_id)
    done = await service.undo_import(batch, owner_user_id=owner_user_id)
    await service.db.commit()
    return dialog_done(
        where_from(request, SECTION.path), _took_back(run_title(batch), done)
    )
