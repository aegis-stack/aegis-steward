"""Settings > Export everything (#623): the whole ledger, in the archive
``finance export`` writes and ``finance restore`` reads.

Built as a job (``imports_job``'s ``export`` run) because a real ledger's
archive takes long enough to stall a web process; the finished frame links
the file it parked in storage, which is handed out once and then deleted.
Admin-only: it is everything.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import Response

from app.components.web_frontend.rendering import templates
from app.components.web_frontend.routes.finance.settings import SECTION
from app.core.time import utcnow
from app.core.uploads import stored_file
from app.services.auth.deps import require_admin
from app.services.finance.service import imports_job

router = APIRouter(
    prefix=SECTION.path + "/export", dependencies=[Depends(require_admin)]
)


def export_path(key: str = "") -> str:
    """Where an export starts, and where its archive downloads."""
    return f"{router.prefix}/{key}" if key else router.prefix


templates.env.globals["export_path"] = export_path


def export_name() -> str:
    return f"steward-{utcnow():%Y-%m-%d}.jsonl.gz"


@router.post("", include_in_schema=False)
async def start(request: Request) -> Response:
    # The whole ledger, every owner's: there is no one owner to scope to.
    job_id = await imports_job.start_import(
        "", file_name=export_name(), account_id=None, owner_user_id=None, kind="export"
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/settings/exporting.html",
        context={"job_id": job_id},
    )


@router.get("/{key:path}", include_in_schema=False)
async def download(key: str) -> Response:
    from app.core.storage import get_storage
    from app.services.finance import portability

    storage = get_storage()
    try:
        archive = await storage.get(key)
        # Storage also holds receipts and uploads: hand out only an export.
        portability.read_header(io.BytesIO(archive or b""))
    except ValueError:  # not a key, or not an export
        raise HTTPException(status_code=404) from None
    # Every export is a new copy of the ledger: none is kept once it left.
    await storage.delete(key)
    return stored_file(
        archive or b"", export_name(), claimed="application/gzip", download=True
    )
