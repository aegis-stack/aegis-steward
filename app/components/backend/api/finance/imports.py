"""File import: upload, preview, batches.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

import asyncio
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import TypeAdapter, ValidationError

from app.components.backend.api.finance.base import _NOT_FOUND, read_upload
from app.services.finance.deps import get_finance_service
from app.services.finance.schemas import (
    ImportBatchResponse,
    ImportBatchSummary,
)
from app.services.finance.service import (
    FinanceImportBatch,
    FinanceService,
    ImportUndone,
    LayoutError,
    can_undo,
    files_in,
)
from app.services.shared.deps import get_owner_user_id

router = APIRouter()

_NO_BATCH = "Import batch not found"


# -- Imports -----------------------------------------------------------------


async def _upload(
    file: UploadFile,
    account_id: int | None,
    service: FinanceService,
    owner_user_id: int | None,
) -> bytes:
    """The checks an upload passes before anything reads it: the size cap,
    and a target account the caller owns."""
    data = await read_upload(file)
    if account_id is not None:
        account = await service.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            )
    return data


async def start_import_job(
    file: UploadFile,
    *,
    account_id: int | None,
    kind: str,
    service: FinanceService,
    owner_user_id: int | None,
) -> str:
    """Check the upload, then ``park_import`` it as ``kind`` of run."""
    data = await _upload(file, account_id, service, owner_user_id)
    return await park_import(
        data,
        file.filename,
        file.content_type,
        account_id=account_id,
        kind=kind,
        owner_user_id=owner_user_id,
    )


async def start_files_job(
    files: list[UploadFile],
    *,
    account_id: int | None,
    kind: str,
    service: FinanceService,
    owner_user_id: int | None,
) -> str:
    """One file as ``start_import_job``; several, or a folder's worth,
    packed into one .zip the job reads file by file (#618). Each file
    passes the same size cap; the account is checked once."""
    if len(files) == 1:
        return await start_import_job(
            files[0],
            account_id=account_id,
            kind=kind,
            service=service,
            owner_user_id=owner_user_id,
        )
    from app.services.finance.service import files_label, pack

    first = await _upload(files[0], account_id, service, owner_user_id)
    bodies = [first, *[await read_upload(file) for file in files[1:]]]
    return await park_import(
        pack([(str(f.filename), body) for f, body in zip(files, bodies, strict=True)]),
        f"{files_label(len(files))}.zip",
        "application/zip",
        account_id=account_id,
        kind=kind,
        owner_user_id=owner_user_id,
    )


async def keep_answers(
    keys: list[str],
    choices: list[str],
    *,
    service: FinanceService,
    owner_user_id: int | None,
) -> None:
    """The review's account answers (#620), kept before the import plans:
    a name with an account id is that account's from now on, a blank one
    becomes a new account. 422 when an answer is not your account."""
    answers = {
        key: int(choice)
        for key, choice in zip(keys, choices, strict=False)
        if choice.isdigit()
    }
    if not answers:
        return
    try:
        await service.remember_account_names(answers, owner_user_id=owner_user_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await service.db.commit()


async def park_import(
    data: bytes,
    file_name: str | None,
    content_type: str | None,
    *,
    account_id: int | None,
    kind: str,
    owner_user_id: int | None,
) -> str:
    """Park checked bytes in storage and hand ``kind`` of run to a job
    (``imports_job.RUNS``). The file is never parsed in this process.

    The bytes go to storage, not into the queue: the worker mounts the
    same volume, and a queue is a poor place to park a file.
    """
    from app.core.storage import get_storage
    from app.services.finance.domains import imports_job

    storage_key = await get_storage().put(data, content_type=content_type)
    return await imports_job.start_import(
        storage_key,
        file_name=file_name,
        account_id=account_id,
        owner_user_id=owner_user_id,
        kind=kind,
    )


async def layout_file_of(
    files: list[UploadFile], layout_file: str
) -> tuple[str, bytes]:
    """The one file a layout is mapped from: of several, or a .zip's
    contents (#618), the one named ``layout_file``, else the first."""
    try:
        named = [
            entry
            for file in files
            # A .zip is unpacked whole, so off the event loop (#487).
            for entry in (
                await asyncio.to_thread(
                    files_in, await read_upload(file), str(file.filename)
                )
            )[0]
        ]
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return next((entry for entry in named if entry[0] == layout_file), named[0])


async def save_csv_layout(
    data: bytes,
    *,
    name: str,
    columns: dict[str, str],
    date_format: str,
    spending_positive: bool,
    service: FinanceService,
    owner_user_id: int | None,
) -> dict[str, Any]:
    """Keep ``columns`` (field -> the file's column) as a layout once it
    reads ``data`` (#619). 422 says what to fix."""
    try:
        profile = await service.save_layout(
            owner_user_id=owner_user_id,
            file_bytes=data,
            name=name,
            columns=columns,
            date_format=date_format,
            spending_positive=spending_positive,
        )
    except LayoutError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await service.db.commit()
    return {"id": profile.id, "name": profile.name}


async def undoable_batch(
    batch_id: int, *, service: FinanceService, owner_user_id: int | None
) -> FinanceImportBatch:
    """The caller's batch, if it can be undone (``can_undo``); else 404."""
    batch = await service.get_import_batch(batch_id, owner_user_id=owner_user_id)
    if batch is None or not can_undo(batch):
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_BATCH)
    return batch


async def take_back(
    batch: FinanceImportBatch, *, service: FinanceService, owner_user_id: int | None
) -> ImportUndone:
    """Take one file back (#621): the rows it added go, the fields it
    changed go back, and a row edited since stays."""
    done = await service.undo_import(batch, owner_user_id=owner_user_id)
    await service.db.commit()
    return done


@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def import_file(
    file: list[UploadFile] = File(...),
    account_id: int | None = None,
    answer_key: list[str] = Form(default_factory=list),
    answer_account: list[str] = Form(default_factory=list),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> dict[str, str]:
    """Upload an OFX/QFX/QIF/CSV/Excel file, several, or a .zip, and
    ingest each under its own batch, undone by
    ``POST /import/batches/{id}/undo``.

    Dispatch is by file extension. QIF/CSV need an ``account_id`` (they carry no
    account info); OFX can resolve its own. Duplicate rows are deduped; an
    identical re-upload short-circuits via the file hash. The review's
    account questions are answered by ``answer_key``/``answer_account``
    pairs (an account id, or blank for a new account).

    Always the import job (#494): only the size and the account are checked
    here, the answer is ``202 {"job_id": ...}``, and the terminal event of
    ``GET /api/v1/jobs/{id}/events`` carries the ``ImportResultResponse``
    fields, or the reason the file was refused.
    """
    await keep_answers(
        answer_key, answer_account, service=service, owner_user_id=owner_user_id
    )
    job_id = await start_files_job(
        file,
        account_id=account_id,
        kind="import",
        service=service,
        owner_user_id=owner_user_id,
    )
    return {"job_id": job_id}


@router.post("/import/preview", status_code=status.HTTP_202_ACCEPTED)
async def preview_import(
    file: list[UploadFile] = File(...),
    account_id: int | None = None,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> dict[str, str]:
    """Dry-run an import: what /import would do with these exact files.

    Same params and dispatch as ``POST /import``, produced from the same
    classification the commit executes — but a pure read. No batch row, no
    auto-created accounts or categories, no transaction writes. The client
    shows this, then re-posts the same bytes to ``/import`` to commit.
    Several files are one review (#618). One write: a CSV no layout knows
    whose column names explain it is saved as the layout for its columns
    and reviewed, how it was read in ``guess`` (#625); one they do not
    explain answers with ``layout_ask``.

    The plan runs as the import job (#494), like the web dialog's review:
    the answer is ``202 {"job_id": ...}`` and the finished job's result is
    the review as ``imports_job.capped_review`` keeps it. A file that
    names no account fails the job with ``imports_job.NEEDS_ACCOUNT``.
    """
    job_id = await start_files_job(
        file,
        account_id=account_id,
        kind="preview",
        service=service,
        owner_user_id=owner_user_id,
    )
    return {"job_id": job_id}


@router.get("/import/batches", response_model=list[ImportBatchSummary])
async def list_import_batches(
    page: int = 1,
    page_size: int = 20,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> list[ImportBatchSummary]:
    """The caller's import batches, newest first."""
    batches = await service.list_import_batches(
        owner_user_id=owner_user_id, page=page, page_size=page_size
    )
    return [ImportBatchSummary.from_row(b) for b in batches]


@router.get("/import/batches/{batch_id}", response_model=ImportBatchResponse)
async def get_import_batch(
    batch_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ImportBatchResponse:
    """Batch review: the run's counts plus every parsed row's outcome."""
    batch = await service.get_import_batch(batch_id, owner_user_id=owner_user_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NO_BATCH)
    rows = await service.list_import_batch_rows(batch_id)
    return ImportBatchResponse.from_batch(batch, rows)


_COLUMNS = TypeAdapter(dict[str, str])


@router.post("/import/layout", status_code=status.HTTP_201_CREATED)
async def save_import_layout(
    file: list[UploadFile] = File(...),
    name: str = Form(...),
    columns: str = Form(...),
    date_format: str = Form(...),
    spending_positive: bool = Form(False),
    layout_file: str = Form(""),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> dict[str, Any]:
    """Answer a preview's ``layout_ask`` (#619): map an unknown CSV once.

    ``columns`` is JSON, field -> the file's column, the shape of
    ``layout_ask.picked``; ``date_format`` one of its ``date_formats``;
    ``spending_positive`` when one amount column shows spending as a
    positive number. Of several files, ``layout_file`` names the one
    (``layout_ask.file_name``). The file must read under the mapping or
    the answer is 422 and nothing is kept; then re-post the same files
    to ``/import/preview``. A layout of yours for the same columns is
    rewritten, its ``id`` kept (a ``guess``'s Change); the ``name`` kept is
    the one asked, numbered when another layout has it.
    """
    try:
        picked = _COLUMNS.validate_json(columns)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "columns is a JSON object of field to column name.",
        ) from exc
    _, data = await layout_file_of(file, layout_file)
    return await save_csv_layout(
        data,
        name=name,
        columns=picked,
        date_format=date_format,
        spending_positive=spending_positive,
        service=service,
        owner_user_id=owner_user_id,
    )


@router.post("/import/batches/{batch_id}/undo", response_model=ImportUndone)
async def undo_import_batch(
    batch_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ImportUndone:
    """Undo one file import (``take_back``); the counts say what it did.
    404 for a batch ``can_undo`` refuses (a sync, an investment ledger,
    one already undone)."""
    batch = await undoable_batch(batch_id, service=service, owner_user_id=owner_user_id)
    return await take_back(batch, service=service, owner_user_id=owner_user_id)
