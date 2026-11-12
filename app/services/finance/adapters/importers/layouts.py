"""A CSV layout nobody knew, mapped once and kept (#619).

An unknown header used to be refused outright. Its columns are mapped
once instead and saved as an import profile, the same data row a seeded
layout is, so the next file with that header is read without asking.
"""

from __future__ import annotations

import asyncio

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import csv_profiles, queries
from app.services.finance.models import FinanceImportProfile
from app.services.finance.schemas.imports import LayoutAsk
from app.services.shared.queries import stored_owner

# What a column can be, in the order the form asks.
FIELDS = (
    ("date", "Date"),
    ("name", "Payee"),
    ("amount", "Amount"),
    ("debit", "Money out"),
    ("credit", "Money in"),
    ("account", "Account"),
    ("category", "Category"),
    ("memo", "Memo"),
)
# How a date can be written, each shown as the 31st of March.
DATE_FORMATS = {
    "%m/%d/%Y": "03/31/2026",
    "%Y-%m-%d": "2026-03-31",
    "%d/%m/%Y": "31/03/2026",
    "%d.%m.%Y": "31.03.2026",
    "%m/%d/%y": "03/31/26",
}


class LayoutError(ValueError):
    """The mapping cannot read the file; the message says what to fix."""


def offered(formats: list[str]) -> dict[str, str]:
    """The date styles a file fits, each with how it looks."""
    return {f: DATE_FORMATS[f] for f in formats if f in DATE_FORMATS}


def layout_ask(
    unknown: csv_profiles.UnknownCsvLayoutError, file_name: str | None
) -> LayoutAsk:
    """The map-once form for a file no layout could read: empty for an
    unknown header; for a known one whose dates read two ways, its
    mapping filled in and only the styles that fit offered."""
    if not isinstance(unknown, csv_profiles.AmbiguousDatesError):
        return LayoutAsk(columns=unknown.header, file_name=file_name)
    profile = unknown.profile
    return LayoutAsk(
        columns=unknown.header,
        file_name=file_name,
        picked={field: column for column, field in profile.column_mapping.items()},
        name=f"My {profile.name}",
        date_formats=offered(unknown.formats),
        reason=(
            f"This looks like a {profile.name} file, but its dates could be "
            "read two ways. Say how they are written, once."
        ),
    )


def _convention(picked: dict[str, str], spending_positive: bool) -> str:
    if "debit" in picked or "credit" in picked:
        return "split_debit_credit"
    if "amount" not in picked:
        raise LayoutError("Pick the amount column, or money out and money in.")
    return "outflow_positive" if spending_positive else "outflow_negative"


async def save_layout(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    file_bytes: bytes,
    name: str,
    columns: dict[str, str],
    date_format: str,
    spending_positive: bool,
) -> FinanceImportProfile:
    """Save ``columns`` (field -> the file's column) as a layout called
    ``name``, once it has read this file without an error."""
    name = name.strip()
    if not name:
        raise LayoutError("Name the layout.")
    header = csv_profiles.header_preview(file_bytes)
    picked = {field: column for field, column in columns.items() if column}
    if not {"date", "name"} <= picked.keys():
        raise LayoutError("Pick the date and payee columns.")
    for column in picked.values():
        if column not in header:
            raise LayoutError(f"This file has no {column} column.")
    if date_format not in DATE_FORMATS:
        raise LayoutError("Pick how the dates are written.")
    profile = FinanceImportProfile(
        owner_user_id=stored_owner(owner_user_id),
        name=name,
        source_format="csv",
        header_signature=header,
        column_mapping={column: field for field, column in picked.items()},
        date_format=date_format,
        amount_sign_convention=_convention(picked, spending_positive),
    )
    if await queries.profile_named(db, name):
        raise LayoutError(f"A layout called {name} already exists.")

    def _reads() -> None:
        _, index = csv_profiles.detect_profile(file_bytes, [profile])
        csv_profiles.parse_csv(file_bytes, profile, header_index=index)

    try:
        # A whole file, so off the event loop (#487).
        await asyncio.to_thread(_reads)
    except ValueError:
        raise LayoutError(
            f"The {picked['date']} column is not written like "
            f"{DATE_FORMATS[date_format]}."
        ) from None
    db.add(profile)
    await db.flush()
    return profile
