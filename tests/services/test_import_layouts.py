"""A layout nobody knew, mapped once and kept (#619).

An unknown CSV used to be refused outright. Now its columns are mapped
once and saved as a layout, which the next file with that header is read
by, the same way a seeded one is.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import layouts
from app.services.finance.adapters.importers.csv_profiles import (
    detect_profile,
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
async def test_a_name_already_taken_is_refused(
    async_db_session: AsyncSession, csv_profiles: None
) -> None:
    await _save(async_db_session)
    with pytest.raises(layouts.LayoutError, match="already"):
        await _save(async_db_session)


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
