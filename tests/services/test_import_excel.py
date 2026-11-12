"""An Excel file reads as its first sheet, through the CSV layouts (#618).

No second parser: the sheet's rows go through the same detection,
map-once and parsing a CSV does. A typed date cell reads whatever date
style the layout names.
"""

from datetime import date, datetime

from app.services.finance.adapters.importers.csv_profiles import (
    detect_profile,
    header_preview,
    parse_csv,
)
from app.services.finance.models import FinanceImportProfile
from app.services.finance.seeds.seed import CSV_IMPORT_PROFILES
from tests.services.app_exports import CHASE, xlsx

PROFILES = [FinanceImportProfile(is_system=True, **p) for p in CSV_IMPORT_PROFILES]


def test_a_sheet_reads_like_the_csv_it_would_have_been() -> None:
    data = xlsx(
        CHASE,
        [
            datetime(2026, 3, 2),
            "03/03/2026",
            "Corner Cafe",
            "Food",
            "Sale",
            -4.75,
            None,
        ],
        ["03/04/2026", "03/04/2026", "Employer", "Income", "Payment", 2500, ""],
    )

    profile, header = detect_profile(data, PROFILES)

    assert profile is not None and profile.name == "Chase Credit Card"
    rows = parse_csv(data, profile, header_index=header)
    assert [(r.date, r.amount, r.name) for r in rows] == [
        (date(2026, 3, 2), -475, "Corner Cafe"),
        (date(2026, 3, 4), 250000, "Employer"),
    ]


def test_an_unknown_sheet_offers_its_columns_to_map() -> None:
    data = xlsx(["Statement for March"], ["When", "Who", "How much"])
    assert header_preview(data) == ["When", "Who", "How much"]
