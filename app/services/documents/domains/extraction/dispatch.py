"""Where an extraction job runs: the worker when the stack has one, else here.

The Extract button, the jobs API and the SSE stream never know which. A
job id comes back either way; progress and the result arrive through the
same endpoints.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.log import logger
from app.services.documents.domains.extraction.jobs import run_extraction
from app.services.system.job_store import RedisJobStore, start_job
from app.services.system.jobs import JobHandle, get_job_runner

# How long a reader that needs the pages now waits on their job.
# ponytail: one bound for every document; a long scan read with vision can
# take longer, so raise it if real ones time out.
WAIT_SECONDS = 300


async def start_extraction_in_process(
    document_id: int, *, owner_user_id: int | None, force: bool
) -> str:
    """Run the extraction as an asyncio task in this process."""

    async def work(handle: JobHandle) -> dict[str, int]:
        return await run_extraction(
            document_id,
            owner_user_id=owner_user_id,
            force=force,
            report=handle.set_label,
        )

    return get_job_runner().start(
        f"documents-extract:{document_id}", work, label="Opening the document..."
    )


async def start_extraction(
    document_id: int, *, owner_user_id: int | None, force: bool
) -> str:
    """Start the extraction as a job: on the worker where the stack has one;
    or return the job already reading this document."""
    name = f"documents-extract:{document_id}"
    if not force:
        # One reading at a time per document. A second ask while the first
        # is still running (an agent calling twice in three seconds, a page
        # refreshed) joins that job rather than starting another pass over
        # the same scan.
        store = RedisJobStore.shared()
        try:
            for job in await store.list_jobs():
                if job.name == name and job.status == "running":
                    return job.job_id
        finally:
            await store.aclose()
    job_id = await start_job(
        name,
        "extract_document_task",
        (document_id, owner_user_id, force),
        lambda report: run_extraction(
            document_id, owner_user_id=owner_user_id, force=force, report=report
        ),
        label="Opening the document...",
    )
    logger.info("documents.extract.started", job_id=job_id, document_id=document_id)
    return job_id


async def read_quietly(document_id: int, *, owner_user_id: int | None) -> None:
    """Read the pages on the worker without anybody asking, and never let
    that fail the thing that filed the document.

    Never forced: a page is read once, and re-filing paper already on
    file must not pay to read it twice. Guarded, because the BYTES are
    the valuable thing - a worker that is down loses the reading, never
    the document, and the reading is offered again from the document.
    """
    try:
        await start_extraction(document_id, owner_user_id=owner_user_id, force=False)
    except Exception:
        logger.exception("documents.extract.not_started", document_id=document_id)


async def extract_and_wait(
    document_id: int, *, owner_user_id: int | None, force: bool
) -> dict[str, Any]:
    """``start_extraction``, waited on: for a reader that needs the pages
    now (a chat turn), so the webserver still renders none where there is
    a worker. The job's result; RuntimeError when it failed or cannot be
    followed from here, TimeoutError past ``WAIT_SECONDS``."""
    job_id = await start_extraction(
        document_id, owner_user_id=owner_user_id, force=force
    )
    runner = get_job_runner()
    queue = await runner.subscribe_any(job_id)
    if queue is None:
        raise RuntimeError(f"Extraction job {job_id} cannot be followed from here")
    last: dict[str, Any] = {}
    async with asyncio.timeout(WAIT_SECONDS):
        async for snapshot in runner.follow(job_id, queue):
            last = snapshot
    if last.get("status") != "done":
        raise RuntimeError(last.get("error") or "The extraction did not finish")
    return last.get("result") or {}


# How long a caller may sit on a reading before it gives the job id back
# instead: a seven-page scan through the vision model is a couple of
# minutes, and the stream says how long it has been quiet the whole time.
WAIT_BUDGET_SECONDS = 180.0
WAIT_POLL_SECONDS = 2.0


async def wait_for_extraction(
    job_id: str, *, budget: float = WAIT_BUDGET_SECONDS
) -> str:
    """Sit on a reading until it lands, fails, or the budget runs out.

    Returns the job's final status - "done", "failed" - or "running" when
    the budget ran out first, so the caller can say the read is still
    going rather than pretend it never started.
    """
    import asyncio

    from app.core.config import settings
    from app.services.system.job_store import RedisJobStore

    store = RedisJobStore.from_url(settings.REDIS_URL)
    try:
        waited = 0.0
        while waited < budget:
            job = await store.get(job_id)
            if job is None or job.status != "running":
                return job.status if job else "done"
            await asyncio.sleep(WAIT_POLL_SECONDS)
            waited += WAIT_POLL_SECONDS
        return "running"
    finally:
        await store.aclose()
