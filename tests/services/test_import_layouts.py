"""A layout nobody knew, mapped once and kept (#619).

An unknown CSV used to be refused outright. Now its columns are mapped
once and saved as a layout, which the next file with that header is read
by, the same way a seeded one is.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import layouts
from app.services.finance.adapters.importers.base import ParsedTransaction
from app.services.finance.adapters.importers.csv_profiles import (
    SAMPLE_ROWS,
    UnknownCsvLayoutError,
    detect_profile,
    header_preview,
    parse_csv,
)
from app.services.finance.adapters.importers.queries import (
    csv_profiles as profiles,
)
from tests.services.app_exports import ynab, ynab_row

FILE = (
    b"Exported by a budgeting app\n"
    b"When,Who,How much,Note\n"
    b"2026-03-02,Corner Cafe,-4.75,latte\n"
    b"2026-03-03,Employer,2500.00,\n"
)
COLUMNS = {"date": "When", "name": "Who", "amount": "How much", "memo": "Note"}


async def _save(db: AsyncSession, data: bytes = FILE, **changes: object) -> None:
    await layouts.save_layout(
        db,
        owner_user_id=None,
        file_bytes=data,
        **{
            "name": "Budget app",
            "columns": COLUMNS,
            "date_format": "%Y-%m-%d",
            "spending_positive": False,
            **changes,
        },  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_a_mapped_layout_reads_the_next_file(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    await _save(async_db_session)

    profile, header = detect_profile(FILE, await profiles(async_db_session))

    assert profile is not None and profile.name == "Budget app"
    rows = parse_csv(FILE, profile, header_index=header)
    assert [(r.date, r.amount, r.name, r.memo) for r in rows] == [
        (date(2026, 3, 2), -475, "Corner Cafe", "latte"),
        (date(2026, 3, 3), 250000, "Employer", ""),
    ]


@pytest.mark.asyncio
async def test_money_out_and_in_columns_read_as_one_amount(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    data = b"Day,Payee,Out,In\n03/02/2026,Corner Cafe,4.75,\n"
    await _save(
        async_db_session,
        data,
        columns={"date": "Day", "name": "Payee", "debit": "Out", "credit": "In"},
        date_format="%m/%d/%Y",
    )
    profile, header = detect_profile(data, await profiles(async_db_session))
    assert profile is not None
    assert [r.amount for r in parse_csv(data, profile, header_index=header)] == [-475]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "says"),
    [
        ({"date_format": "%m/%d/%Y"}, "When"),
        ({"columns": {**COLUMNS, "date": "Posted"}}, "Posted"),
        ({"columns": {"date": "When", "name": "Who"}}, "amount"),
        ({"name": " "}, "Name"),
    ],
)
async def test_a_mapping_that_cannot_read_the_file_says_why(
    async_db_session: AsyncSession, csv_profiles: None, changes: dict, says: str
) -> None:
    with pytest.raises(layouts.LayoutError, match=says):
        await _save(async_db_session, **changes)


@pytest.mark.asyncio
@pytest.mark.queryspy(threshold=3)  # the same layout saved twice, on purpose
async def test_mapping_the_same_columns_again_rewrites_the_layout(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    """#625: the review's Change maps a guessed layout again; files with
    these columns are read the new way, not by the first of two."""
    await _save(async_db_session)
    await _save(async_db_session, columns={**COLUMNS, "memo": ""})

    mine = [p for p in await profiles(async_db_session) if not p.is_system]
    assert [(p.name, "Note" in p.column_mapping) for p in mine] == [
        ("Budget app", False)
    ]


@pytest.mark.asyncio
@pytest.mark.queryspy(threshold=3)  # two layouts saved, on purpose
async def test_a_name_already_taken_gets_a_number(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    await _save(async_db_session)
    other = b"Day,Payee,Out,In\n03/02/2026,Corner Cafe,4.75,\n"
    await _save(
        async_db_session,
        other,
        columns={"date": "Day", "name": "Payee", "debit": "Out", "credit": "In"},
        date_format="%m/%d/%Y",
    )

    names = [p.name for p in await profiles(async_db_session) if not p.is_system]
    assert names == ["Budget app", "Budget app (2)"]


def _walk(*rows: tuple[int, int]) -> list[ParsedTransaction]:
    return [
        ParsedTransaction(
            date=date(2026, 11, 1), amount=a, source="csv", running_balance=b
        )
        for a, b in rows
    ]


@pytest.mark.parametrize(
    ("rows", "matches"),
    [
        (_walk((-8417, 241583), (185000, 426583)), True),  # oldest first
        (_walk((185000, 426583), (-8417, 241583)), True),  # newest first
        (_walk((8417, 241583), (-185000, 426583)), False),  # in and out swapped
        (_walk((-8417, 241583)), None),  # one balance proves nothing
    ],
)
def test_the_amounts_are_checked_against_the_running_balance(
    rows: list[ParsedTransaction], matches: bool | None
) -> None:
    assert layouts.balance_matches(rows) is matches


@pytest.mark.asyncio
async def test_your_layout_for_a_known_header_is_read_first(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    """A YNAB file whose dates read two ways is mapped once with its
    style; from then on that mapping, not the seeded YNAB, reads it."""
    data = ynab(ynab_row("03/04/2026", "Cafe", "$4.75", "$0.00"))
    await _save(
        async_db_session,
        data,
        name="My YNAB",
        columns={
            "date": "Date",
            "name": "Payee",
            "debit": "Outflow",
            "credit": "Inflow",
        },
        date_format="%d/%m/%Y",
    )
    profile, header = detect_profile(data, await profiles(async_db_session))
    assert profile is not None and profile.name == "My YNAB"
    assert parse_csv(data, profile, header_index=header)[0].date == date(2026, 4, 3)


def test_the_ask_shows_the_rows_under_the_header() -> None:
    """#625: the preamble line is passed over, a blank line skipped, and
    no more than ``SAMPLE_ROWS`` rows ride along."""
    body = b"".join(b"2026-03-%02d,Shop,-1.00,\n" % day for day in range(1, 9))
    data = FILE.replace(b"2026-03-03", b"\n2026-03-03") + body
    unknown = UnknownCsvLayoutError(header_preview(data), [])

    ask = layouts.layout_ask(unknown, "budget.csv", data)

    assert ask.columns == ["When", "Who", "How much", "Note"]
    assert ask.rows[:2] == [
        ["2026-03-02", "Corner Cafe", "-4.75", "latte"],
        ["2026-03-03", "Employer", "2500.00", ""],
    ]
    assert len(ask.rows) == SAMPLE_ROWS


def test_the_ask_opens_with_what_the_column_names_suggest() -> None:
    """#625: a guess from the file's own names and dates, to confirm;
    a column no name explains is left to the person."""
    data = (
        b"Posted Date,Description,Withdrawal,Deposit,Running Balance\n"
        b"11/03/2026,Grocery,84.17,,2415.83\n"
        b"11/14/2026,Water,62.40,,2353.43\n"
    )
    unknown = UnknownCsvLayoutError(header_preview(data), [])

    ask = layouts.layout_ask(unknown, "checking.csv", data)

    assert ask.picked == {
        "date": "Posted Date",
        "name": "Description",
        "debit": "Withdrawal",
        "credit": "Deposit",
        "balance": "Running Balance",
    }
    assert ask.name == "checking"
    # Only the reading every sample date fits, told in the file's own date.
    assert ask.date_formats == {"%m/%d/%Y": "11/03/2026 is November 3, 2026"}
