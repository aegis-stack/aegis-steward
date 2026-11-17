"""One extraction, run as a job, wherever the job runs.

The worker task and the in-process runner both call ``run_extraction``;
they differ only in how progress gets back to whoever is watching, which
is the ``report`` callable each passes in. The worker's entry
(``run_extraction_job``) ships only with a worker to run it.
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_async_session
from app.services.documents.domains.extraction.pages import extract_document
from app.services.documents.domains.extraction.vision import vision_reader
from app.services.documents.domains.reading.proposals import read_and_propose
from app.services.system.job_store import narrate
from app.services.system.jobs import Report


def progress_label(page: int, total: int) -> str:
    return f"Reading page {page} of {total}..."


async def run_extraction(
    document_id: int,
    *,
    owner_user_id: int | None,
    force: bool,
    report: Report,
) -> dict[str, int]:
    """Extract in its own session; ``report`` receives each page's label."""
    async with get_async_session() as session:
        result = await extract_document(
            session,
            document_id,
            owner_user_id=owner_user_id,
            vision=await vision_reader(),
            force=force,
            progress=lambda page, total: report(progress_label(page, total)),
        )
        await session.commit()
    # Extraction PROPOSES: what the document says about itself goes in
    # front of somebody rather than into the record.
    #
    # Handed a way to OPEN a database rather than this open one: reading
    # what a letter DEMANDS is a model call, and a session held across it
    # is the application's write lock held across it. The reading owns
    # its own session boundaries either side of the model.
    await read_and_propose(get_async_session, document_id, owner_user_id=owner_user_id)
    return result.as_dict()


async def run_extraction_job(
    job_id: str, document_id: int, owner_user_id: int | None, force: bool
) -> dict[str, Any]:
    """The worker's entry: narrate into the shared job store, then finish."""
    return await narrate(
        job_id,
        lambda report: run_extraction(
            document_id, owner_user_id=owner_user_id, force=force, report=report
        ),
    )
