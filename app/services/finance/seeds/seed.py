"""Seed finance reference data: currencies + CSV import profiles.

Idempotent — safe to run on every boot. Sync ``Session`` API to match the
startup hook in ``database_init.py``. Import profiles are DATA (header
signature + column mapping + sign convention), so a new bank-CSV layout is a
new row here, not a new parser.
"""

import logging

from sqlmodel import Session, col

from app.core.seed import seed_rows
from app.services.finance.models import FinanceCurrency, FinanceImportProfile

logger = logging.getLogger(__name__)

DEFAULT_CURRENCIES = [
    {"code": "usd", "name": "US Dollar", "symbol": "$", "decimals": 2},
    {"code": "eur", "name": "Euro", "symbol": "€", "decimals": 2},
    {"code": "gbp", "name": "British Pound", "symbol": "£", "decimals": 2},
]

# Header signatures copied from real exports; column_mapping is csv-column ->
# canonical field; amount_sign_convention drives sign normalization (AMEX
# reports charges as positive, so its profile negates — no if-statement).
CSV_IMPORT_PROFILES = [
    {
        "name": "Chase Credit Card",
        "source_format": "csv",
        "header_signature": [
            "Transaction Date",
            "Post Date",
            "Description",
            "Category",
            "Type",
            "Amount",
            "Memo",
        ],
        "column_mapping": {
            "Transaction Date": "date",
            "Description": "name",
            "Amount": "amount",
            "Category": "category",
            "Memo": "memo",
        },
        "date_format": "%m/%d/%Y",
        "amount_sign_convention": "outflow_negative",
    },
    {
        "name": "Chase Checking",
        "source_format": "csv",
        "header_signature": [
            "Details",
            "Posting Date",
            "Description",
            "Amount",
            "Type",
            "Balance",
            "Check or Slip #",
        ],
        "column_mapping": {
            "Posting Date": "date",
            "Description": "name",
            "Amount": "amount",
            "Check or Slip #": "check_number",
        },
        "date_format": "%m/%d/%Y",
        "amount_sign_convention": "outflow_negative",
    },
    {
        "name": "American Express",
        "source_format": "csv",
        "header_signature": ["Date", "Description", "Amount"],
        "column_mapping": {
            "Date": "date",
            "Description": "name",
            "Amount": "amount",
        },
        "date_format": "%m/%d/%Y",
        "amount_sign_convention": "outflow_positive",
    },
    {
        # Quicken Mac "Register Transactions to CSV" export — a report with a
        # title/preamble before this header row (the importer scans past it).
        "name": "Quicken Mac Register",
        "source_format": "csv",
        "header_signature": [
            "",
            "Scheduled",
            "Split",
            "Date",
            "Check #",
            "Payee",
            "Category",
            "Tags",
            "Amount",
            "Balance",
        ],
        "column_mapping": {
            "Date": "date",
            "Payee": "name",
            "Amount": "amount",
            "Balance": "balance",
            "Check #": "check_number",
            "Category": "category",
            "Scheduled": "scheduled",
        },
        "date_format": "%m/%d/%Y",
        "amount_sign_convention": "outflow_negative",
    },
    {
        # Quicken "All Transactions" report — every account in one file, each
        # row tagged with its owning account (last column). The pipeline routes
        # rows to per-name accounts (auto-creating missing ones). No running
        # balance in this layout; "Payee/Security" doubles as the payee.
        "name": "Quicken All Transactions",
        "source_format": "csv",
        "header_signature": [
            "",
            "Split",
            "Date",
            "Payee/Security",
            "Category",
            "Tags",
            "Amount",
            "Account",
        ],
        "column_mapping": {
            "Date": "date",
            "Payee/Security": "name",
            "Amount": "amount",
            "Category": "category",
            "Tags": "tags",
            "Account": "account",
            # Present only when the user includes scheduled bills in the
            # export; mapped so those rows are recognized, never posted.
            "Scheduled": "scheduled",
        },
        "date_format": "%m/%d/%Y",
        "amount_sign_convention": "outflow_negative",
    },
    # Other finance apps' transaction exports (#619). None of the four
    # publishes its header; each is verbatim from real exports (sources in
    # tests/services/test_import_app_exports.py). Every one names its
    # account per row, so rows route by it like Quicken All Transactions.
    {
        # The first eight columns never changed; Owner, Reviewed, Id and
        # more were added after them in 2025-2026, which detection allows.
        "name": "Monarch",
        "source_format": "csv",
        "header_signature": [
            "Date",
            "Merchant",
            "Category",
            "Account",
            "Original Statement",
            "Notes",
            "Amount",
            "Tags",
        ],
        "column_mapping": {
            "Date": "date",
            "Merchant": "name",
            "Category": "category",
            "Account": "account",
            "Notes": "memo",
            "Amount": "amount",
            "Tags": "tags",
        },
        "date_format": "%Y-%m-%d",
        "amount_sign_convention": "outflow_negative",
    },
    {
        # Dates follow the user's YNAB setting; the file is read in the one
        # style every date fits, and asked about when two do.
        "name": "YNAB",
        "source_format": "csv",
        "header_signature": [
            "Account",
            "Flag",
            "Date",
            "Payee",
            "Category Group/Category",
            "Category Group",
            "Category",
            "Memo",
            "Outflow",
            "Inflow",
            "Cleared",
        ],
        "column_mapping": {
            "Account": "account",
            "Date": "date",
            "Payee": "name",
            "Category": "category",
            "Memo": "memo",
            "Outflow": "debit",
            "Inflow": "credit",
        },
        "date_format": "%m/%d/%Y|%d/%m/%Y|%d.%m.%Y|%Y-%m-%d",
        "amount_sign_convention": "split_debit_credit",
    },
    {
        # Money out is positive, money in negative. A spreadsheet re-save
        # turns its dates into 7/31/26.
        "name": "Copilot",
        "source_format": "csv",
        "header_signature": [
            "date",
            "name",
            "amount",
            "status",
            "category",
            "parent category",
            "excluded",
            "tags",
            "type",
            "account",
            "account mask",
            "note",
            "recurring",
        ],
        "column_mapping": {
            "date": "date",
            "name": "name",
            "amount": "amount",
            "category": "category",
            "tags": "tags",
            "account": "account",
            "note": "memo",
        },
        "date_format": "%Y-%m-%d|%m/%d/%y",
        "amount_sign_convention": "outflow_positive",
    },
    {
        "name": "Empower",
        "source_format": "csv",
        "header_signature": [
            "Date",
            "Account",
            "Description",
            "Category",
            "Tags",
            "Amount",
        ],
        "column_mapping": {
            "Date": "date",
            "Account": "account",
            "Description": "name",
            "Category": "category",
            "Tags": "tags",
            "Amount": "amount",
        },
        "date_format": "%Y-%m-%d|%m/%d/%Y",
        "amount_sign_convention": "outflow_negative",
    },
]


def seed_finance_tables(session: Session) -> None:
    """Create default currencies + CSV import profiles if absent."""
    seed_rows(session, FinanceCurrency, "code", DEFAULT_CURRENCIES)

    # Before the profiles, not with them. A profile's ``currency`` is a
    # foreign key onto ``code``, which is not the primary key, so the
    # dependency is invisible to the insert sort - and the startup
    # session runs with ``autoflush=False``, so nothing would reach the
    # database until a commit that orders the children first and fails.
    session.flush()

    # Only system (ownerless) profiles count as present: a user may own a
    # profile with the same name.
    seed_rows(
        session,
        FinanceImportProfile,
        "name",
        [{**profile, "is_system": True} for profile in CSV_IMPORT_PROFILES],
        col(FinanceImportProfile.owner_user_id).is_(None),
    )

    session.commit()
