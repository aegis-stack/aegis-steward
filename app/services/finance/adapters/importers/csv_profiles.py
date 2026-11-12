"""CSV import driven by ``finance_import_profile`` rows (data, not code).

Chase-CC / Chase-checking / AMEX layouts are auto-detected by header signature;
AMEX's inverted sign is handled by the profile's ``amount_sign_convention``,
not an if-statement. Rows are id-less, so they use LANE 2 — the same content
hash as QIF (assigned by the pipeline), ``source='csv'``.
"""

from __future__ import annotations

from collections.abc import Callable
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import io
import re
from typing import TYPE_CHECKING

from app.services.finance.adapters.importers.base import ParsedTransaction
from app.services.finance.utils import to_cents

if TYPE_CHECKING:
    from app.services.finance.models import FinanceImportProfile


class UnknownCsvLayoutError(ValueError):
    """Raised when no profile matches an uploaded CSV's header row."""

    def __init__(
        self,
        header: list[str],
        available: list[str],
        *,
        batch_id: int | None = None,
    ) -> None:
        self.header = header
        self.available = available
        self.batch_id = batch_id
        super().__init__(
            f"No import profile matches CSV header {header}. "
            f"Available profiles: {available}."
        )


class AmbiguousDatesError(UnknownCsvLayoutError):
    """A known layout whose dates read more than one way (``03/04``: March
    or April?): which style the file uses is asked, not guessed."""

    def __init__(
        self, header: list[str], profile: FinanceImportProfile, formats: list[str]
    ) -> None:
        super().__init__(header, [profile.name])
        self.profile = profile
        self.formats = formats
        self.args = (f"The dates in this {profile.name} file read more than one way.",)


# An .xlsx is a zip; a CSV never starts this way.
_XLSX_MAGIC = b"PK\x03\x04"
# How a sheet's typed date cell is written out: what no CSV writes.
_SHEET_DATE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _read_rows(data: bytes) -> list[list[str]]:
    if data.startswith(_XLSX_MAGIC):
        return _sheet_rows(data)
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def _cell(value: object) -> str:
    if value is None:
        return ""
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _sheet_rows(data: bytes) -> list[list[str]]:
    """An Excel file's first sheet as the CSV it would have been (#618),
    a typed date written ISO, which ``_parse_date`` reads in any layout.
    ponytail: reread per call (detect, then parse); cache if sheets grow."""
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        rows = [
            [_cell(value) for value in row]
            for row in book.worksheets[0].iter_rows(values_only=True)
        ]
    finally:
        book.close()
    # A sheet pads every row to its widest; a CSV row ends where it ends.
    for row in rows:
        while row and row[-1] == "":
            row.pop()
    return rows


def header_preview(data: bytes) -> list[str]:
    """The likeliest header of an unknown layout: the widest of the first
    rows, so a title or preamble line before it is passed over."""
    rows = [[cell.strip() for cell in row] for row in _read_rows(data)[:20]]
    return max(rows, key=lambda row: sum(1 for cell in row if cell), default=[])


def _row_matches(row: list[str], profile: FinanceImportProfile) -> bool:
    trimmed = [cell.strip() for cell in row]
    signature = [cell.strip() for cell in profile.header_signature]
    if trimmed == signature:
        return True
    # set-equality fallback (same columns, reordered) — length-guarded so a
    # short preamble line can't accidentally match.
    return len(trimmed) == len(signature) and set(trimmed) == set(signature)


# Fields a layout may leave out without becoming a different layout: a
# single-account Quicken register report drops ``Scheduled``, and parsing
# already reads every one of these as absent-is-None.
OPTIONAL_FIELDS = frozenset({"balance", "check_number", "scheduled"})


def _required(profile: FinanceImportProfile) -> set[str]:
    """The signature columns a file must carry to be this layout."""
    mapping = profile.column_mapping or {}
    return {
        cell.strip()
        for cell in profile.header_signature
        if cell.strip() and mapping.get(cell.strip()) not in OPTIONAL_FIELDS
    }


def _row_contains(row: list[str], profile: FinanceImportProfile) -> bool:
    """The row carries every required signature column, plus extras.

    Vendors ADD columns (Quicken's "All Transactions" report grew a
    ``Scheduled`` column) and DROP optional ones (its single-account
    register report has none). Parsing addresses columns by name, so
    both are harmless - only detection was brittle. Requiring the full
    required set is its own guard: a two-cell preamble row can never
    contain six header names.
    """
    required = _required(profile)
    if len(required) < 3:
        return False  # too weak a signature to match loosely
    return required <= {cell.strip() for cell in row}


def detect_profile(
    data: bytes, profiles: list[FinanceImportProfile]
) -> tuple[FinanceImportProfile | None, int]:
    """Find the header row + matching profile.

    Scans every row (not just the first) so a title/preamble before the real
    header — as Quicken Mac's "report" CSV exports produce — is skipped.
    Exact matches win over "signature present, with extra columns" ones, so
    a newly-added vendor column can't steer a file to a looser profile.
    Returns ``(profile, header_row_index)`` or ``(None, -1)``.
    """
    rows = _read_rows(data)
    for index, row in enumerate(rows):
        for profile in profiles:
            if _row_matches(row, profile):
                return profile, index
    for index, row in enumerate(rows):
        cells = {cell.strip() for cell in row}
        loose = [p for p in profiles if _row_contains(row, p)]
        if loose:
            # The most specific layout wins: the one with the most of its
            # signature actually present, so a looser profile whose
            # required columns happen to fit cannot claim the file.
            return max(loose, key=lambda p: len(set(p.header_signature) & cells)), index
    return None, -1


def _parse_amount_cents(raw: str) -> int:
    """Parse a money cell to signed cents. ``$``/thousands stripped;
    ``(45.00)`` (accounting negative) -> -4500. Always exact via Decimal."""
    # Whatever currency marks it (``$``, ``RM``, ``€``) and thousands
    # separators go; the digits, the point and the sign stay.
    cleaned = re.sub(r"[^\d.()-]", "", raw)
    if not cleaned:
        return 0
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        cents = to_cents(Decimal(cleaned))
    except InvalidOperation:
        return 0
    return -abs(cents) if negative else cents


def _row_amount(get: Callable[[str], str | None], profile: FinanceImportProfile) -> int:
    convention = profile.amount_sign_convention
    if convention == "split_debit_credit":
        debit = get("debit")
        credit = get("credit")
        debit_cents = _parse_amount_cents(debit) if debit else 0
        credit_cents = _parse_amount_cents(credit) if credit else 0
        return credit_cents - abs(debit_cents)  # debit outflow, credit inflow
    cents = _parse_amount_cents(get("amount") or "")
    if convention == "outflow_positive":  # AMEX: charges positive -> negate
        return -cents
    return cents  # outflow_negative: trust the source sign


def _parse_date(raw: str, date_format: str) -> date:
    raw = raw.strip()
    try:
        return datetime.strptime(raw, date_format).date()
    except ValueError:
        if _SHEET_DATE.fullmatch(raw):
            return datetime.fromisoformat(raw).date()
        raise


def _reads(cells: list[str], date_format: str) -> list[date] | None:
    try:
        return [_parse_date(cell, date_format) for cell in cells]
    except ValueError:
        return None


def _date_format(
    cells: list[str], profile: FinanceImportProfile, header: list[str]
) -> tuple[str, dict[str, date]]:
    """The style this file writes dates in, and the dates it already read.
    A layout may name several, ``|``-separated (YNAB writes the user's own
    setting): the one every date reads with. Two that read the file
    differently are asked about."""
    formats = (profile.date_format or "").split("|")
    if len(formats) == 1:
        return formats[0], {}
    fits = {f: read for f in formats if (read := _reads(cells, f)) is not None}
    if len({tuple(read) for read in fits.values()}) > 1:
        raise AmbiguousDatesError(header, profile, list(fits))
    chosen = next(iter(fits), formats[0])
    return chosen, dict(zip(cells, fits.get(chosen, []), strict=False))


def parse_csv(
    data: bytes, profile: FinanceImportProfile, *, header_index: int = 0
) -> list[ParsedTransaction]:
    """Parse CSV bytes into ``ParsedTransaction`` records per ``profile``.

    ``header_index`` is where the column header lives (from ``detect_profile``);
    everything before it (title/preamble) and blank rows are skipped.
    """
    rows = _read_rows(data)
    if header_index >= len(rows):
        return []
    header = [cell.strip() for cell in rows[header_index]]
    index_of = {name: i for i, name in enumerate(header)}
    mapping = profile.column_mapping  # csv column -> canonical field

    body = [row for row in rows[header_index + 1 :] if any(c.strip() for c in row)]
    date_column = next((c for c, f in mapping.items() if f == "date"), None)
    at = index_of.get(date_column or "")
    cells = [row[at] for row in body if at is not None and at < len(row) and row[at]]
    date_format, read = _date_format(cells, profile, header)

    parsed: list[ParsedTransaction] = []
    for row in body:

        def get(canonical: str, _row: list[str] = row) -> str | None:
            for csv_column, canon in mapping.items():
                if canon == canonical and csv_column in index_of:
                    idx = index_of[csv_column]
                    return _row[idx] if idx < len(_row) else None
            return None

        date_raw = get("date")
        if not date_raw:
            continue
        cents = _row_amount(get, profile)
        check_number = get("check_number")
        # Running balance is a raw signed figure (not an inflow/outflow), so it
        # is parsed directly, never through the amount sign convention.
        balance_raw = get("balance")
        running_balance = (
            _parse_amount_cents(balance_raw)
            if balance_raw and balance_raw.strip()
            else None
        )
        # Multi-account exports (e.g. a Quicken "All Transactions" report) name
        # the owning account per row; it routes the pipeline's account resolver.
        account_raw = get("account")
        account_key = (
            account_raw.strip() if account_raw and account_raw.strip() else None
        )
        # Any non-empty value in a mapped "scheduled" column marks a row the
        # source considers not-yet-posted. Quicken uses several ("Scheduled",
        # "Overdue", "DueToday"), so the VALUE is not interpreted - its
        # presence is the signal, which keeps unknown vocabularies working.
        scheduled_raw = get("scheduled")
        parsed.append(
            ParsedTransaction(
                is_scheduled=bool(scheduled_raw and scheduled_raw.strip()),
                date=read.get(date_raw) or _parse_date(date_raw, date_format),
                amount=cents,
                source="csv",
                name=get("name"),
                original_description=get("name"),
                memo=get("memo"),
                check_number=check_number.strip() if check_number else None,
                category_hint=get("category"),
                tags=get("tags"),
                raw_amount=cents,
                raw_sign_convention=profile.amount_sign_convention,
                running_balance=running_balance,
                account_key=account_key,
            )
        )
    return parsed
