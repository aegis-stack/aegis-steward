"""File import: upload, preview, batches.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.components.backend.api.finance.base import _NOT_FOUND, read_upload
from app.services.finance.deps import get_finance_service
from app.services.finance.schemas import (
    ImportBatchResponse,
    ImportBatchSummary,
)
from app.services.finance.service import FinanceService
from app.services.shared.deps import get_owner_user_id

router = APIRouter()


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
    ingest each under its own reversible batch.

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
    Several files are one review (#618).

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found"
        )
    rows = await service.list_import_batch_rows(batch_id)
    return ImportBatchResponse.from_batch(batch, rows)
