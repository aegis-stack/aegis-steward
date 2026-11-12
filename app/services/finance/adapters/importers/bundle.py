"""Several files, or a whole folder, in one review (#618).

The upload is packed into one .zip, so the job keeps its one stored
file; the job reads it file by file. Each file is planned as itself,
the reviews add up into one, and each file is its own import (its own
batch, its own Undo in Settings > Activity). A .zip someone drops in
reads the same way.
"""

from __future__ import annotations

import io
from pathlib import PurePosixPath
from typing import Any
import zipfile

from app.core.config import settings
from app.services.finance.adapters.importers.base import (
    READS,
    ImportResult,
    _extension,
)
from app.services.finance.schemas.imports import (
    AccountQuestion,
    ImportPreviewResponse,
    import_result_payload,
)

# Several files at once: ten of the largest an import takes.
_BUNDLE_MAX_BYTES = 10 * settings.IMPORT_MAX_BYTES
# The counts a review or a run adds up, read off the models.
_RESULT_COUNTS = [f for f in ImportResult.model_fields if f.startswith("rows_")]
_REVIEW_COUNTS = [
    *(f for f in ImportPreviewResponse.model_fields if f.startswith("rows_")),
    "category_kept_count",
]


def pack(files: list[tuple[str, bytes]]) -> bytes:
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in files:
            bundle.writestr(name, data)
    return raw.getvalue()


def files_in(data: bytes, file_name: str) -> tuple[list[tuple[str, bytes]], list[str]]:
    """(name, bytes) of each file this app reads, and the names it leaves
    out. Anything but a .zip is one file. A name is its path in the zip,
    so two folders' statement.csv stay two. A folder's own clutter
    (.DS_Store, a Mac's __MACOSX copies) is not worth naming."""
    if _extension(file_name) != "zip":
        return [(file_name, data)], []
    files, skipped = _unzip(data)
    if not files:
        raise ValueError("None of these is a file this app reads.")
    return files, skipped


def files_label(count: int) -> str:
    """What several files are called while they travel as one."""
    return f"{count} files"


def _unzip(data: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    files: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        members = [
            info
            for info in bundle.infolist()
            if not info.is_dir()
            and not PurePosixPath(info.filename).name.startswith(".")
            and "__MACOSX" not in PurePosixPath(info.filename).parts
        ]
        # What the zip says it unpacks to, before any of it is read.
        if sum(info.file_size for info in members) > _BUNDLE_MAX_BYTES:
            raise ValueError("These files are more than one import takes.")
        for info in members:
            if _extension(info.filename) not in READS:
                skipped.append(info.filename)
            elif info.file_size > settings.IMPORT_MAX_BYTES:
                raise ValueError(f"{info.filename} is larger than an import takes.")
            else:
                files.append((info.filename, bundle.read(info)))
    return files, skipped


def _span(dates: Any, pick: Any) -> Any:
    """The earliest or latest of these dates, skipping the missing."""
    return pick((d for d in dates if d), default=None)


def _one(values: list[str | None]) -> str | None:
    """The value every file shares, else none."""
    return values[0] if len(set(values)) == 1 else None


def merge_reviews(reviews: list[ImportPreviewResponse]) -> ImportPreviewResponse:
    """One review for several files. Each was planned alone, so a row in
    two of them counts in both here; the import itself, file after file,
    keeps it once (ponytail: plan them as one if that gap misleads)."""
    by_account: dict[str, int] = {}
    asked: dict[str, AccountQuestion] = {}
    for review in reviews:
        for name, count in review.inserts_by_account.items():
            by_account[name] = by_account.get(name, 0) + count
        for question in review.account_questions:
            if (seen := asked.get(question.key)) is None:
                asked[question.key] = question.model_copy()
                continue
            seen.rows += question.rows
            seen.suggested_id = seen.suggested_id or question.suggested_id
            seen.date_start = _span((seen.date_start, question.date_start), min)
            seen.date_end = _span((seen.date_end, question.date_end), max)

    def total(field: str) -> int:
        return sum(getattr(review, field) for review in reviews)

    def span(field: str, pick: Any) -> Any:
        return _span((getattr(r, field) for r in reviews), pick)

    def union(field: str) -> list[str]:
        return sorted({name for r in reviews for name in getattr(r, field)})

    return ImportPreviewResponse(
        file_name=files_label(len(reviews)),
        layout=_one([r.layout for r in reviews]),
        account_name=_one([r.account_name for r in reviews]),
        accounts_total=max(r.accounts_total for r in reviews),
        date_start=span("date_start", min),
        date_end=span("date_end", max),
        insert_date_start=span("insert_date_start", min),
        insert_date_end=span("insert_date_end", max),
        inserts_by_account=by_account,
        new_accounts=union("new_accounts"),
        removed_accounts=union("removed_accounts"),
        new_categories=union("new_categories"),
        account_questions=list(asked.values()),
        account_choices=next(
            (r.account_choices for r in reviews if r.account_choices), []
        ),
        edits=[edit for review in reviews for edit in review.edits],
        **{field: total(field) for field in _REVIEW_COUNTS},
    )


def merge_results(results: list[ImportResult]) -> dict[str, Any]:
    """The done screen for several files: the counts added up. Each file
    is its own run, undone from Settings > Activity."""
    stated = [r.balances for r in results if r.balances is not None]
    merged = ImportResult(
        balances=[check for checks in stated for check in checks] if stated else None,
        **{f: sum(getattr(r, f) for r in results) for f in _RESULT_COUNTS},
    )
    return {
        **import_result_payload(merged),
        "files_total": len(results),
    }
