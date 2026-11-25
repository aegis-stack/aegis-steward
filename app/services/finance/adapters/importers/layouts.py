"""A CSV layout nobody knew, mapped once and kept (#619).

An unknown header used to be refused outright. Its columns are mapped
once instead and saved as an import profile, the same data row a seeded
layout is, so the next file with that header is read without asking.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import csv_profiles, queries
from app.services.finance.adapters.importers.base import ParsedTransaction
from app.services.finance.models import FinanceImportProfile
from app.services.finance.schemas.imports import LayoutAsk, LayoutGuess, ReadRow
from app.services.shared.queries import stored_owner

if TYPE_CHECKING:
    from app.services.finance.adapters.importers.plan import ImportPlan

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
    ("balance", "Running balance"),
)
# How a date can be written, each shown as the 31st of March.
DATE_FORMATS = {
    "%m/%d/%Y": "03/31/2026",
    "%Y-%m-%d": "2026-03-31",
    "%d/%m/%Y": "31/03/2026",
    "%d.%m.%Y": "31.03.2026",
    "%m/%d/%y": "03/31/26",
}


# What a column's own name suggests it holds, first match wins. A guess
# that reads the whole file opens the review as a layout, shown and one
# Change away; one that does not opens the form with it (#625).
_HINTS = (
    ("date", ("date",)),
    ("name", ("payee", "description", "merchant", "name")),
    ("debit", ("withdrawal", "debit", "money out", "outflow")),
    ("credit", ("deposit", "credit", "money in", "inflow")),
    ("amount", ("amount",)),
    ("account", ("account",)),
    ("category", ("category",)),
    ("memo", ("memo", "note")),
    ("balance", ("balance",)),
)


class LayoutError(ValueError):
    """The mapping cannot read the file; the message says what to fix."""


def date_choices(
    columns: list[str],
    rows: list[list[str]],
    column: str | None,
    formats: list[str] | None = None,
) -> dict[str, str]:
    """The styles of ``formats`` (default: all) that every sample date in
    ``column`` fits, each told as what the file's first date means that
    way. With no dates to read, each style's example instead.

    ponytail: told from the guessed date column; a re-pick in the browser
    keeps these labels, and save says when the style does not fit."""
    styles = [f for f in formats or DATE_FORMATS if f in DATE_FORMATS]
    at = columns.index(column) if column in columns else None
    cells = [r[at] for r in rows if at is not None and at < len(r) and r[at]]

    def read(style: str) -> list[datetime] | None:
        try:
            return [datetime.strptime(cell, style) for cell in cells]
        except ValueError:
            return None

    told = {
        style: f"{cells[0]} is {day:%B} {day.day}, {day.year}"
        for style in styles
        if cells and (days := read(style)) and (day := days[0])
    }
    return told or {style: DATE_FORMATS[style] for style in styles}


def layout_ask(
    unknown: csv_profiles.UnknownCsvLayoutError, file_name: str | None, data: bytes
) -> LayoutAsk:
    """The map-once form for a file no layout could read: empty for an
    unknown header; for a known one whose dates read two ways, its
    mapping filled in and only the styles that fit offered."""
    rows = csv_profiles.header_and_sample(data)[1]
    if not isinstance(unknown, csv_profiles.AmbiguousDatesError):
        picked = _suggested(unknown.header)
        choices = date_choices(unknown.header, rows, picked.get("date"))
        return LayoutAsk(
            columns=unknown.header,
            rows=rows,
            file_name=file_name,
            name=(file_name or "My file").rsplit(".", 1)[0],
            picked=picked,
            date_formats=choices,
        )
    profile = unknown.profile
    picked = {field: column for column, field in profile.column_mapping.items()}
    return LayoutAsk(
        columns=unknown.header,
        rows=rows,
        file_name=file_name,
        picked=picked,
        name=f"My {profile.name}",
        date_formats=date_choices(
            unknown.header, rows, picked.get("date"), unknown.formats
        ),
        reason=(
            f"This looks like a {profile.name} file, but its dates could be "
            "read two ways. Say how they are written, once."
        ),
    )


def _suggested(columns: list[str]) -> dict[str, str]:
    """Field -> column, from the columns' names (``_HINTS``)."""
    picked: dict[str, str] = {}
    for field, words in _HINTS:
        column = next(
            (
                c
                for c in columns
                if c not in picked.values() and any(w in c.lower() for w in words)
            ),
            None,
        )
        if column is not None:
            picked[field] = column
    return picked


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
    verify: bool = True,
) -> FinanceImportProfile:
    """Save ``columns`` (field -> the file's column) as a layout called
    ``name`` (numbered when taken), once it has read this file without an
    error; ``verify=False`` leaves that to a caller about to parse it
    anyway. A layout of yours for the same header is rewritten."""
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
    # Files with these columns are read one way: a second map of the same
    # header (the review's Change) rewrites the first, never a rival.
    same = next(
        (
            p
            for p in await queries.csv_profiles(db)
            if not p.is_system and csv_profiles.row_matches(header, p)
        ),
        None,
    )
    if same is None or same.name != name:
        profile.name = await _free_name(db, name)

    def _reads() -> None:
        _, index = csv_profiles.detect_profile(file_bytes, [profile])
        csv_profiles.parse_csv(file_bytes, profile, header_index=index)

    try:
        # A whole file, so off the event loop (#487).
        if verify:
            await asyncio.to_thread(_reads)
    except ValueError:
        raise LayoutError(
            f"The {picked['date']} column is not written like "
            f"{DATE_FORMATS[date_format]}."
        ) from None
    if same is not None:
        for key in ("name", "column_mapping", "date_format", "amount_sign_convention"):
            setattr(same, key, getattr(profile, key))
        profile = same
    db.add(profile)
    await db.flush()
    return profile


async def _free_name(db: AsyncSession, name: str) -> str:
    """``name``, or ``name (2)`` and on, whichever no layout is called."""
    taken = await queries.profile_names(db)
    free, n = name, 1
    while free in taken:
        n += 1
        free = f"{name} ({n})"
    return free


def balance_matches(parsed: list[ParsedTransaction]) -> bool | None:
    """Whether the amounts walk the file's running balance on every row,
    newest-first or oldest-first; None with fewer than two balances. The
    check that money in and out, and the sign, were read right."""
    pairs = [
        (t.amount, t.running_balance) for t in parsed if t.running_balance is not None
    ]
    if len(pairs) < 2 or len(pairs) < len(parsed):
        return None
    steps = list(zip(pairs, pairs[1:], strict=False))
    oldest_first = all(b1 - b0 == a1 for (_, b0), (a1, b1) in steps)
    newest_first = all(b0 - b1 == a0 for (a0, b0), (_, b1) in steps)
    return oldest_first or newest_first


async def read_as_guessed(
    db: AsyncSession,
    unknown: csv_profiles.UnknownCsvLayoutError,
    ask: LayoutAsk,
    data: bytes,
    file_name: str,
    account_id: int | None,
    owner_user_id: int | None,
) -> tuple[ImportPlan, LayoutGuess | None] | None:
    """The plan, read with what the column names suggest and saved as the
    layout for these columns (#625), and how it was read for the review;
    None when the guess cannot stand alone and the form asks instead. A
    guess stands when ``save_layout`` takes it, its dates read one way,
    and - a lone amount column carries no sign rule - the amounts walk
    the running balance. Asked for an account, the plan comes back with
    no guess and nothing kept: the next try guesses again and shows it.
    A kept guess is pending in its savepoint; the caller commits."""
    from app.services.finance.adapters.importers.preview import preview_file

    if isinstance(unknown, csv_profiles.AmbiguousDatesError):
        return None
    if len(ask.date_formats) != 1:
        return None
    savepoint = await db.begin_nested()
    try:
        await save_layout(
            db,
            owner_user_id=owner_user_id,
            file_bytes=data,
            name=ask.name or file_name,
            columns=ask.picked,
            date_format=next(iter(ask.date_formats)),
            spending_positive=False,
            verify=False,  # the preview parses it next
        )
        plan = await preview_file(
            db,
            owner_user_id=owner_user_id,
            file_name=file_name,
            file_bytes=data,
            account_id=account_id,
        )
    except ValueError:  # LayoutError, or a date the guess cannot read
        await savepoint.rollback()
        return None
    if plan.needs_account:
        await savepoint.rollback()
        return plan, None
    walks = balance_matches(plan.parsed)
    if "amount" in ask.picked and walks is not True:
        await savepoint.rollback()
        return None
    await savepoint.commit()
    rows = [
        ReadRow(day=t.date, name=t.name, amount=t.amount)
        for t in plan.parsed[: csv_profiles.SAMPLE_ROWS]
    ]
    return plan, LayoutGuess(ask=ask, rows=rows, balance_matches=walks)
