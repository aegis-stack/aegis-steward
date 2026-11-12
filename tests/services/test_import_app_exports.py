"""Other finance apps' exports are known layouts (#619).

Each header is verbatim from real exports (none of the four apps
publishes one): Monarch from a year of weekly exports and its staff's
column notes, YNAB from seven real register exports, Copilot from two
real exports, Empower from six. The rows are made up, shaped like the
real ones: each app's sign, date style, quoting and account naming.
"""

from datetime import date

import pytest

from app.services.finance.adapters.importers.csv_profiles import (
    AmbiguousDatesError,
    detect_profile,
    parse_csv,
)
from app.services.finance.models import FinanceImportProfile
from app.services.finance.seeds.seed import CSV_IMPORT_PROFILES
from tests.services.app_exports import BOM, ynab, ynab_row

PROFILES = [FinanceImportProfile(is_system=True, **p) for p in CSV_IMPORT_PROFILES]
# app -> (export bytes, the account its rows name)
EXPORTS = {
    "Monarch": (
        b"Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags,"
        b"Owner,Reviewed,Reviewed At,Reviewed By,Pending,Id\r\n"
        b"2026-03-02,Corner Cafe,Coffee Shops,Signature Visa (...2562),"
        b'"CORNER CAFE 12, LLC",,-4.75,,Shared,,,,false,1\r\n'
        b"2026-03-03,Employer,Paychecks,Signature Visa (...2562),PAYROLL,,"
        b"2500.00,,Shared,,,,false,2\r\n",
        "Signature Visa (...2562)",
    ),
    "YNAB": (
        ynab(
            ynab_row("2026-03-02", "Corner Cafe", "$4.75", "$0.00"),
            ynab_row("2026-03-03", "Employer", "$0.00", "$2500.00"),
        ),
        "Joint Checking",
    ),
    "Copilot": (
        (
            BOM + '"date","name","amount","status","category","parent category",'
            '"excluded","tags","type","account","account mask","note","recurring"\n'
            '"2026-03-02","Corner Cafe","4.75","posted","Coffee","Food","false",'
            '"","regular","Adv Plus Banking","0372","",""\n'
            '"2026-03-03","Employer","-2500.00","posted","Paycheck","Income",'
            '"false","","income","Adv Plus Banking","0372","",""\n'
        ).encode(),
        "Adv Plus Banking",
    ),
    "Empower": (
        b"Date,Account,Description,Category,Tags,Amount\n"
        b'2026-03-02,"Platinum Card - Ending in 1002","Corner Cafe","Restaurants",'
        b",-4.75\n"
        b'2026-03-03,"Platinum Card - Ending in 1002","Employer","Paychecks",'
        b",2500\n",
        "Platinum Card - Ending in 1002",
    ),
}


def _read(data: bytes) -> tuple[str, list[tuple[date, int, str | None, str | None]]]:
    profile, header = detect_profile(data, PROFILES)
    assert profile is not None
    rows = parse_csv(data, profile, header_index=header)
    return profile.name, [(r.date, r.amount, r.name, r.account_key) for r in rows]


@pytest.mark.parametrize("app", sorted(EXPORTS))
def test_an_apps_export_is_known_and_read_its_way(app: str) -> None:
    data, account = EXPORTS[app]

    name, rows = _read(data)

    assert name == app
    assert rows == [
        (date(2026, 3, 2), -475, "Corner Cafe", account),
        (date(2026, 3, 3), 250000, "Employer", account),
    ]


def test_monarchs_first_eight_columns_are_enough() -> None:
    """The header grew at the end over 2025-2026; the first eight never
    changed, and an export from before Owner is the same layout."""
    data = (
        b"Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        b"2025-02-24,Corner Cafe,Coffee Shops,Main (...4156),CAFE,,-4.75,\n"
    )
    assert _read(data)[0] == "Monarch"


@pytest.mark.parametrize(
    ("day", "on"),
    [
        ("31/05/2026", date(2026, 5, 31)),
        ("27.02.2026", date(2026, 2, 27)),
        ("2026-02-27", date(2026, 2, 27)),
        ("05/28/2026", date(2026, 5, 28)),
    ],
)
def test_ynab_dates_are_read_in_the_style_the_file_uses(day: str, on: date) -> None:
    """YNAB writes dates the way the user set them; real exports carry
    all four styles."""
    data = ynab(ynab_row(day, "Corner Cafe", "$4.75", "$0.00"))
    assert _read(data)[1][0][0] == on


def test_ynab_dates_that_read_two_ways_are_asked_about() -> None:
    data = ynab(
        ynab_row("03/02/2026", "Corner Cafe", "$4.75", "$0.00"),
        ynab_row("04/02/2026", "Corner Cafe", "$4.75", "$0.00"),
    )
    with pytest.raises(AmbiguousDatesError) as asked:
        _read(data)
    assert asked.value.profile.name == "YNAB"


def test_an_amount_in_another_currency_is_read_not_zeroed() -> None:
    """A YNAB plan in ringgit writes ``RM378.00``; it used to read as 0."""
    data = ynab(ynab_row("2026-05-31", "Ikea", "RM378.00", "RM0.00"))
    assert _read(data)[1][0][1] == -37800


def test_empower_dates_resaved_by_a_spreadsheet_still_read() -> None:
    data = (
        b"Date,Account,Description,Category,Tags,Amount\n"
        b"12/31/2024,Credit Card 2637,Corner Cafe,Restaurants,,-25.92\n"
    )
    assert _read(data)[1] == [
        (date(2024, 12, 31), -2592, "Corner Cafe", "Credit Card 2637")
    ]
