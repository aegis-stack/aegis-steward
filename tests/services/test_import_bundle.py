"""Several files, or a whole folder, in one review (#618).

The upload is packed into one .zip the job reads file by file: each
file is planned as itself, the reviews add up into one, and each file
is its own import.
"""

from datetime import date
import io
import zipfile

from app.services.finance.adapters.importers.base import AccountQuestion, ImportResult
from app.services.finance.adapters.importers.bundle import (
    files_in,
    merge_results,
    merge_reviews,
    pack,
)
from app.services.finance.schemas import ImportPreviewResponse


def test_a_bundle_unpacks_to_the_files_this_app_reads() -> None:
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as bundle:
        bundle.writestr("statements/", "")
        bundle.writestr("statements/march.csv", b"a")
        bundle.writestr("statements/april.QFX", b"b")
        bundle.writestr("statements/.DS_Store", b"junk")
        bundle.writestr("__MACOSX/statements/._march.csv", b"junk")
        bundle.writestr("statements/notes.pdf", b"c")

    files, skipped = files_in(raw.getvalue(), "statements.zip")

    assert files == [
        ("statements/march.csv", b"a"),
        ("statements/april.QFX", b"b"),
    ]
    assert skipped == ["statements/notes.pdf"]


def test_one_file_is_itself() -> None:
    assert files_in(b"x", "march.csv") == ([("march.csv", b"x")], [])


def test_what_is_packed_unpacks() -> None:
    files = [("a.csv", b"1"), ("b.qif", b"2")]
    assert files_in(pack(files), "2 files.zip") == (files, [])


def test_reviews_add_up() -> None:
    def review(**fields: object) -> ImportPreviewResponse:
        return ImportPreviewResponse(rows_total=2, **fields)  # type: ignore[arg-type]

    asked = AccountQuestion(key="Visa (...1886)", rows=1, date_start=date(2026, 3, 2))
    merged = merge_reviews(
        [
            review(
                rows_inserted=2,
                layout="Monarch",
                date_start=date(2026, 3, 2),
                date_end=date(2026, 3, 9),
                inserts_by_account={"Checking": 2},
                account_questions=[asked],
                account_choices=[(1, "Checking")],
            ),
            review(
                rows_duplicate=2,
                layout="Monarch",
                date_start=date(2026, 2, 1),
                date_end=date(2026, 3, 1),
                inserts_by_account={"Checking": 1},
                new_accounts=["Savings"],
                account_questions=[asked.model_copy(update={"rows": 3})],
            ),
        ]
    )

    assert merged.file_name == "2 files"
    assert (merged.rows_total, merged.rows_inserted, merged.rows_duplicate) == (4, 2, 2)
    assert merged.layout == "Monarch"
    assert (merged.date_start, merged.date_end) == (date(2026, 2, 1), date(2026, 3, 9))
    assert merged.inserts_by_account == {"Checking": 3}
    assert merged.new_accounts == ["Savings"]
    [question] = merged.account_questions
    assert (question.key, question.rows) == ("Visa (...1886)", 4)
    assert merged.account_choices == [(1, "Checking")]


def test_reviews_of_different_layouts_name_none() -> None:
    merged = merge_reviews(
        [
            ImportPreviewResponse(rows_total=1, layout="Monarch"),
            ImportPreviewResponse(rows_total=1, layout="YNAB"),
        ]
    )
    assert merged.layout is None


def test_results_add_up_and_each_file_stays_its_own_run() -> None:
    merged = merge_results(
        [
            ImportResult(batch_id=7, rows_total=2, rows_inserted=2, balances=[]),
            ImportResult(batch_id=8, rows_total=3, rows_inserted=3),
        ]
    )

    assert (merged["rows_inserted"], merged["files_total"]) == (5, 2)
    assert merged["batch_id"] is None and merged["undoable"] is False
    assert merged["balances"] == []
