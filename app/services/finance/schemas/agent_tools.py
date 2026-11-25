"""What the agent's finance tools return, as types.

Code mode prints each tool's return type in the signature the model
codes against. Typed ``dict[str, Any]``, every tool read ``-> dict``, so
her scripts guessed keys - all eight of one call read
``bill_candidates(...)['transactions']`` (the key was 'candidates'),
got nothing, and she proposed ids she made up. A key lives here once.
Each ``*_cents`` number also arrives with its ``*_usd`` beside it
(``with_dollars``, after the tool returns, so declared NotRequired):
display text, never computed on.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class TransactionRow(TypedDict):
    id: int  # what a proposal's 'transaction_id' takes
    date: str
    payee: str | None
    amount_cents: int  # signed, negative = outflow
    amount_usd: NotRequired[str]
    category: str | None
    category_id: int | None
    uncategorized: bool
    account: str | None
    tags: list[str]
    memo: str | None
    transfer: bool
    # income | spending | unfiled | transfer | split | not counted (#316)
    counts_as: str | None
    pending: bool
    bill_id: int | None  # the bill (``bills``' id) it is matched to


class TransactionsSummary(TypedDict):
    """The returned rows' figures, counted as every spending total counts
    them ('counts_as'): print this, not a second script that sums."""

    complete: bool  # False: more rows match than came back (raise limit)
    spending_cents: int  # charges less credits: what the rows cost
    charges_cents: int
    credits_cents: int  # refunds and credits filed as spending
    income_cents: int
    by_payee: dict[str, int]  # spending cents, biggest first
    by_category: dict[str, int]
    not_in_spending: dict[str, int]  # rows counted as something else: how many


class Transactions(TypedDict):
    total: int
    returned: int
    transactions: list[TransactionRow]
    summary: TransactionsSummary
    error: NotRequired[str]  # a filter that names nothing (an unknown tag)


class Bill(TypedDict):
    id: int  # what a proposal's 'stream_id' takes
    name: str | None
    direction: str
    frequency: str
    amount_cents: int | None
    amount_usd: NotRequired[str]
    amount_is_declared: bool
    account: str | None
    account_id: int | None
    category: str | None
    next_expected_date: str | None
    last_date: str | None


class Bills(TypedDict):
    bills: list[Bill]


class BillWithCandidates(TypedDict):
    stream_id: int
    name: str | None
    due_date: str | None
    candidates: list[TransactionRow]  # likeliest first


class BillCandidates(TypedDict):
    bills: list[BillWithCandidates]


class CleanupRow(TransactionRow):
    """An uncategorized row with the best evidence the ledger holds for
    it: the payee's precedent, or the overdue bill it could be paying."""

    evidence: str | None  # precedent | bill | None
    suggested_category: str | None
    suggested_category_id: int | None  # a transaction.categorize's category_id
    candidate_bill_id: int | None  # the stream a recurring.match takes
    bill_name: str | None


class Cleanup(TypedDict):
    days: int
    total: int
    uncategorized: list[CleanupRow]  # newest first


class DueBill(TypedDict):
    name: str
    date: str  # when the walk pays it (an overdue bill lands today)
    due_date: str | None
    amount_cents: int
    amount_usd: NotRequired[str]
    category: str | None
    bill_id: int | None


class ProjectionPoint(TypedDict):
    date: str
    name: str
    direction: str
    amount_cents: int
    amount_usd: NotRequired[str]
    balance_cents: int
    balance_usd: NotRequired[str]
    account: str | None
    category: str | None
    bill_id: int | None  # null for a non-bill point


class Projection(TypedDict):
    as_of: str
    horizon_days: int
    start_balance_cents: int
    start_balance_usd: NotRequired[str]
    end_balance_cents: int
    end_balance_usd: NotRequired[str]
    upcoming_total_cents: int
    upcoming_total_usd: NotRequired[str]
    bills: list[DueBill]
    points: list[ProjectionPoint]


class PlanPoint(TypedDict):
    year: int
    age: int | None
    net_worth_cents: int


class RetirementIncome(TypedDict):
    name: str
    kind: str | None
    monthly_cents: int
    starts: str


class RetirementPlan(TypedDict):
    """The plan to retirement (#351-#353): what was assumed, where the
    money stands by type, the line to the end age and the band of
    simulated returns around it, with the chance the plan holds."""

    as_of: str
    plan_saved: bool
    assumptions: dict[str, Any]
    today: dict[str, Any]
    at_retirement: PlanPoint | None
    at_end: PlanPoint
    band: dict[str, list[Any]]
    chance_of_holding: float
    runs: int
    incomes: list[RetirementIncome]


class CashFlowFigures(TypedDict):
    income: int  # cents, as every figure here
    spending: int
    unfiled: int
    saved: int


class MonthToDate(TypedDict):
    through_day: int
    this_month: CashFlowFigures
    last_month_same_days: CashFlowFigures  # compare a part month with this


class LedgerMonth(TypedDict):
    month: str
    income_cents: int
    income_usd: NotRequired[str]
    spend_cents: int
    spend_usd: NotRequired[str]
    net_cents: int
    net_usd: NotRequired[str]
    unfiled_cents: int  # credits filed as nothing: in neither figure
    unfiled_usd: NotRequired[str]


class LedgerMonths(TypedDict):
    """``ledger``'s monthly detail; its transaction detail is ``Transactions``."""

    scope: str  # what is counted: say it with a figure
    month_to_date: MonthToDate
    months: list[LedgerMonth]  # oldest first


class Category(TypedDict):
    id: int  # what a categorize proposal's 'category_id' takes
    name: str
    classification: str  # expense | income | transfer


class Categories(TypedDict):
    categories: list[Category]


class Tag(TypedDict):
    id: int
    name: str  # what a tag proposal takes
    count: int


class Tags(TypedDict):
    tags: list[Tag]


class Quote(TypedDict):
    found: bool
    ticker: str
    name: NotRequired[str]  # the rest only when found
    close_cents: NotRequired[int]
    close_usd: NotRequired[str]
    as_of: NotRequired[str]


class BudgetLine(TypedDict):
    category: str | None
    category_id: int | None
    payee: str | None
    payee_key: str | None
    limit_cents: int
    limit_usd: NotRequired[str]
    spent_cents: int
    spent_usd: NotRequired[str]
    rolls_over: bool
    carried_cents: int
    carried_usd: NotRequired[str]
    remaining_cents: int
    remaining_usd: NotRequired[str]
    status: str  # good | warn | critical; real only on a limit


class BudgetStats(TypedDict):
    flexible_spent_cents: int
    flexible_allocated_cents: int
    days_left_in_period: int
    over_budget_count: int
    over_budget_labels: list[str]
    fixed_total_cents: int
    left_in_limits_under_budget_cents: int
    net_left_cents: int


class Budget(TypedDict):
    period_month: int  # YYYYMM
    limits: list[BudgetLine]  # what the user set
    commitments: list[BudgetLine]  # bills for context: never a limit
    stats: BudgetStats
    changed_since: dict[str, int] | None  # an ended month filed into since


class Holding(TypedDict):
    ticker: str | None
    name: str | None
    quantity: float
    market_value_cents: int
    market_value_usd: NotRequired[str]


class Upcoming(TypedDict):
    name: str
    date: str
    amount_cents: int  # signed: inflows positive, bills negative
    amount_usd: NotRequired[str]


class Envelope(TypedDict):
    credit_cents: int | None  # per cadence period
    cadence: str
    auto_credit: bool
    pays_for_tag: str | None


class Lien(TypedDict):
    account: str
    lien_position: int | None


class Property(TypedDict):
    kind: str
    valuation_source: str
    valuation_as_of: str | None
    is_estimate: bool | None
    purchase_price_cents: int | None
    purchase_date: str | None
    ownership_share_bps: int
    include_in_net_worth: bool
    equity_cents: NotRequired[int]  # these three only when a loan is linked
    ltv_bps: NotRequired[int]
    liens: NotRequired[list[Lien]]


class Goal(TypedDict):
    target_cents: int
    target_date: str | None
    status: str
    monthly_contribution_cents: int | None
    priority: int


class Liability(TypedDict):
    type: str | None
    interest_rate_bps: int | None
    minimum_payment_cents: int | None
    next_payment_due: str | None
    last_statement_balance_cents: int | None
    last_payment_cents: int | None
    last_payment_date: str | None
    ytd_interest_paid_cents: int | None
    ytd_principal_paid_cents: int | None


class Account(TypedDict):
    id: int
    name: str
    account_type: str
    classification: str
    balance_cents: int  # liabilities negative = owed
    balance_usd: NotRequired[str]
    hidden: bool
    closed_on: str | None
    counts_in_net_worth: bool  # net worth sums exactly these
    whose: str | None  # None = ours
    subject_id: int | None
    held_with: str | None
    reference: str | None
    envelope: NotRequired[Envelope]
    property: NotRequired[Property]
    goal: NotRequired[Goal]
    holdings: NotRequired[list[Holding]]
    upcoming: NotRequired[list[Upcoming]]  # the next 35 days
    liability: NotRequired[Liability]


class Accounts(TypedDict):
    accounts: list[Account]


class Charge(TypedDict):
    """A transaction as a match shortlist names it (``candidate_row``): bills,
    claims and a matter's charges read one shape."""

    id: int  # what a proposal's 'transaction_id' takes
    date: str
    payee: str | None
    amount_cents: int  # signed, negative = outflow
    amount_usd: NotRequired[str]
    account_id: int


class Charges(TypedDict):
    total_cents: int  # signed
    total_usd: NotRequired[str]
    items: list[Charge]
