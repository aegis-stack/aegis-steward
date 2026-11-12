"""CSV/OFX and investment import pipeline shapes.

A topic module of the ``schemas`` package; every name here is
re-exported from the package root, which stays the one import path.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, computed_field

if TYPE_CHECKING:
    from app.services.finance.models import (
        FinanceImportBatch,
        FinanceImportBatchRow,
    )


class AccountQuestion(BaseModel):
    """An account name the ledger does not know (#620), asked before
    Import; see ``importers/account_names``."""

    key: str
    suggested_id: int | None = None
    rows: int = 0
    date_start: date | None = None
    date_end: date | None = None


class BalanceCheck(BaseModel):
    """A balance the file states, against the ledger on its date (#622)."""

    account_id: int
    account_name: str
    as_of: date
    # As a statement prints it (a debt as what is owed): what Correct the
    # balance is filled in with.
    printed: int
    gap: int  # file minus ledger; 0 when they agree


class LayoutAsk(BaseModel):
    """What the map-once form opens with (#619): the file's columns, and
    for a known layout whose dates read two ways, its mapping filled in,
    the styles that fit, and why it asks."""

    columns: list[str]
    file_name: str | None = None
    picked: dict[str, str] = Field(default_factory=dict)
    name: str | None = None
    # Format -> example, only the styles that fit.
    date_formats: dict[str, str] = Field(default_factory=dict)
    reason: str | None = None


class ImportResultResponse(BaseModel):
    """Summary returned right after an import run."""

    batch_id: int | None
    rows_total: int
    rows_inserted: int
    rows_updated: int
    rows_duplicate: int
    rows_error: int
    # Not posted money (scheduled / future-dated): recorded, never ledgered.
    rows_skipped: int = 0
    # Rows for accounts the user removed - never written, never resurrected.
    rows_ignored: int = 0
    # None when nothing was checked (an identical re-upload); [] when the
    # file states no balance.
    balances: list[BalanceCheck] | None = None
    # Several files imported at once (#618), each its own run.
    files_total: int = 1
    # The one Undo rule (#621), so the done screen offers what the route takes.
    undoable: bool = False


def import_result_payload(result: Any, *, undoable: bool = False) -> dict[str, Any]:
    """An ``ImportResult`` as the dict both contracts share.

    Here rather than in the API router it used to live in: the worker
    needs the same dict and importing a router to get it brought FastAPI
    and five more backend modules into a process that serves no HTTP -
    8 MiB, measured 2026-09-19. A shape belongs with the shapes.
    """
    return ImportResultResponse(
        batch_id=result.batch_id,
        rows_total=result.rows_total,
        rows_inserted=result.rows_inserted,
        rows_updated=result.rows_updated,
        rows_duplicate=result.rows_duplicate,
        rows_error=result.rows_error,
        rows_skipped=result.rows_skipped,
        rows_ignored=result.rows_ignored,
        balances=result.balances,
        undoable=undoable,
    ).model_dump(mode="json")


class ImportPreviewEdit(BaseModel):
    """One transaction an import would update in place, with the exact
    field changes — shown to the user BEFORE anything is written."""

    transaction_id: int
    date: date
    amount: int
    name: str | None = None
    account: str | None = None
    changes: list[str]
    # The source app re-categorized this row but the user set the category
    # by hand here, so the import keeps the user's choice.
    category_kept: bool = False


class ImportPreviewResponse(BaseModel):
    """A dry-run classification of an import file: what a commit would do.

    Produced from the same plan the commit executes, and writing nothing —
    counts here match the subsequent ``ImportResultResponse`` exactly."""

    file_name: str | None = None
    rows_total: int
    # Set when these exact bytes were already imported: re-importing is a
    # no-op, so there is nothing to preview.
    identical_batch_id: int | None = None
    # A single-account layout previewed with no target account: the client
    # asks which account the statement belongs to, then previews again.
    needs_account: bool = False
    # A CSV layout to map once (#619): an unknown one, or a known one
    # whose dates read two ways.
    layout_ask: LayoutAsk | None = None
    layout: str | None = None
    account_name: str | None = None
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_duplicate: int = 0
    rows_error: int = 0
    rows_skipped: int = 0
    # Rows for accounts the user removed - never written, never resurrected.
    rows_ignored: int = 0
    # The whole file: how many accounts and what span it covers (#619).
    accounts_total: int = 0
    date_start: date | None = None
    date_end: date | None = None
    insert_date_start: date | None = None
    insert_date_end: date | None = None
    # Account display name -> how many new transactions land there.
    inserts_by_account: dict[str, int] = Field(default_factory=dict)
    # Accounts / categories the commit would create.
    new_accounts: list[str] = Field(default_factory=list)
    removed_accounts: list[str] = Field(default_factory=list)
    # Files a folder held that this app does not read (#618).
    files_skipped: list[str] = Field(default_factory=list)
    # Names the ledger does not know, each asked before Import (#620),
    # and your accounts, (id, name), an answer can pick.
    account_questions: list[AccountQuestion] = Field(default_factory=list)
    account_choices: list[tuple[int, str]] = Field(default_factory=list)
    new_categories: list[str] = Field(default_factory=list)
    edits: list[ImportPreviewEdit] = Field(default_factory=list)
    category_kept_count: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def changes(self) -> int:
        """Rows a commit would write: added plus changed in place.

        On the wire because every client's confirm button counts them, and
        a count computed once per UI is a count that drifts.
        """
        return self.rows_inserted + self.rows_updated

    @computed_field  # type: ignore[prop-decorator]
    @property
    def nothing_to_import(self) -> bool:
        """True when the review has nothing to offer an Import button.

        Two shapes of the same dead end: the byte-identical re-upload, and
        a fresh export whose every row is already stored (yesterday's
        import, or a sync, got there first). Parse errors disqualify — a
        file that partly failed deserves the full review, not a shrug.
        """
        if self.identical_batch_id is not None:
            return True
        return not self.changes and not self.rows_error


class ImportBatchSummary(BaseModel):
    """An import batch without its rows — for the batch list."""

    id: int
    source_type: str
    file_name: str | None
    status: str
    rows_total: int
    rows_inserted: int
    rows_duplicate: int
    rows_error: int

    @classmethod
    def from_row(cls, batch: FinanceImportBatch) -> ImportBatchSummary:
        return cls(
            id=batch.id,
            source_type=batch.source_type,
            file_name=batch.file_name,
            status=batch.status,
            rows_total=batch.rows_total,
            rows_inserted=batch.rows_inserted,
            rows_duplicate=batch.rows_duplicate,
            rows_error=batch.rows_error,
        )


class ImportBatchRowResponse(BaseModel):
    row_number: int
    parsed_status: str
    matched_transaction_id: int | None = None
    fitid: str | None = None
    reason: str | None = None

    @classmethod
    def from_row(cls, row: FinanceImportBatchRow) -> ImportBatchRowResponse:
        return cls(
            row_number=row.row_number,
            parsed_status=row.parsed_status,
            matched_transaction_id=row.matched_transaction_id,
            fitid=row.fitid,
            reason=row.reason,
        )


class ImportBatchResponse(BaseModel):
    """An import batch plus its per-row outcomes (the review view)."""

    id: int
    source_type: str
    file_name: str | None
    status: str
    rows_total: int
    rows_inserted: int
    rows_duplicate: int
    rows_error: int
    rows: list[ImportBatchRowResponse]

    @classmethod
    def from_batch(
        cls, batch: FinanceImportBatch, rows: list[FinanceImportBatchRow]
    ) -> ImportBatchResponse:
        return cls(
            id=batch.id,
            source_type=batch.source_type,
            file_name=batch.file_name,
            status=batch.status,
            rows_total=batch.rows_total,
            rows_inserted=batch.rows_inserted,
            rows_duplicate=batch.rows_duplicate,
            rows_error=batch.rows_error,
            rows=[ImportBatchRowResponse.from_row(r) for r in rows],
        )


class InvestmentImportPosition(BaseModel):
    """One security's replayed ending position - what the ledger says you
    hold once every row is applied. ``value`` is cents at the security's
    LAST price seen in the ledger - the freshest mark the file itself can
    honestly claim, not a live quote."""

    name: str
    shares: float
    value: int


class InvestmentImportPreviewResponse(BaseModel):
    """Parse-only look at an activity ledger: what it carries and what it
    replays to, before any account is chosen or anything is written."""

    activities_parsed: int
    first_date: date
    last_date: date
    total_value: int  # cents, sum of position values
    positions: list[InvestmentImportPosition]


class InvestmentImportResultResponse(BaseModel):
    """Outcome of a custodian activity-ledger import (investments lane)."""

    activities_parsed: int
    trades_inserted: int
    trades_updated: int
    securities_created: int
    securities_matched: int
    account_id: int
    account_name: str
    account_created: bool
