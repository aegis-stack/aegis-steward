"""Finance service facade: what callers outside it import (``app.services.shared.facade``)."""

# ruff: noqa: F401

from typing import TYPE_CHECKING

from app.services.shared import facade

if TYPE_CHECKING:
    from app.services.finance.adapters.importers.base import (
        READS,
        UPLOADS,
        formats_label,
    )
    from app.services.finance.adapters.importers.bundle import (
        files_in,
        files_label,
        merge_results,
        merge_reviews,
        pack,
    )
    from app.services.finance.adapters.importers.csv_profiles import (
        UnknownCsvLayoutError,
        header_and_sample,
    )
    from app.services.finance.adapters.importers.layouts import (
        DATE_FORMATS,
        FIELDS,
        LayoutError,
        date_choices,
        layout_ask,
        read_as_guessed,
    )
    from app.services.finance.adapters.importers.runs import (
        run_state,
        run_summary,
        run_title,
    )
    from app.services.finance.adapters.importers.undo import ImportUndone, can_undo
    from app.services.finance.adapters.providers import connections
    from app.services.finance.adapters.providers.connections import arrivals, placing
    from app.services.finance.adapters.providers.plaid import (
        PLAID_KEYS,
        PLAID_WEBHOOK_PATH,
        set_runtime_webhook_url,
    )
    from app.services.finance.adapters.providers.queries import connection_by_id_live
    from app.services.finance.adapters.providers.simplefin import DEMO_PAGE
    from app.services.finance.adapters.providers.snaptrade import (
        SNAPTRADE_KEYS,
        SnapTradeError,
    )
    from app.services.finance.constants import INCOME_KINDS
    from app.services.finance.domains import imports_job
    from app.services.finance.domains.detection import (
        declare_recurring,
        detect_recurring,
        generate_insights,
        plan_recurring,
        promote_curated_streams,
    )
    from app.services.finance.domains.detection import queries as detection_queries
    from app.services.finance.domains.detection.analyst import (
        existing_note,
        load_finance_agent_fixtures,
        run_analyst_note,
    )
    from app.services.finance.domains.detection.analyst.live_engines import (
        ENGINE_SEEDS,
        HER_REALTIME_DEFAULTS,
    )
    from app.services.finance.domains.detection.analyst.prompts import LIVE_SIGN_OFF
    from app.services.finance.domains.detection.analyst.shared import (
        FINANCE_VOICE_AGENT_SLUG,
        STANDALONE_USER_ID,
    )
    from app.services.finance.domains.detection.insights.commitments import (
        commitment_rollup,
        is_commitment,
        is_paused,
        stream_staleness,
    )
    from app.services.finance.domains.detection.insights.formatting import (
        format_apr,
        format_usd,
    )
    from app.services.finance.domains.detection.insights.rules import (
        create_insight_if_new,
    )
    from app.services.finance.domains.detection.insights.statement_gaps import (
        check_statement,
    )
    from app.services.finance.domains.detection.transfers.answers import (
        break_pair,
        confirm_pair,
        decline_offer,
    )
    from app.services.finance.domains.imports_job import NEEDS_ACCOUNT, run_import_job
    from app.services.finance.domains.investments import queries as investments_queries
    from app.services.finance.domains.investments.activity import replay_positions
    from app.services.finance.domains.investments.loader import (
        import_investment_activities,
    )
    from app.services.finance.domains.investments.optum import (
        UnknownActivityTypeError,
        parse_optum_settled_transactions,
    )
    from app.services.finance.domains.investments.securities import (
        list_current_holdings,
        market_value_cents,
    )
    from app.services.finance.domains.ledger import (
        changelog,
        links,
        merging,
        reimbursements,
        views,
    )
    from app.services.finance.domains.ledger import queries as ledger_queries
    from app.services.finance.domains.ledger.accounts import (
        account_transaction_totals,
        effective_balance,
        liability_details,
        register_balance_as_of,
        statement_balance,
    )
    from app.services.finance.domains.ledger.cash_flow import monthly_cashflow
    from app.services.finance.domains.ledger.categories import (
        list_categories,
        spending_by_category,
    )
    from app.services.finance.domains.ledger.hydrate import hydrate_transactions
    from app.services.finance.domains.ledger.institutions import websites
    from app.services.finance.domains.ledger.merchant_icon import (
        ICON_PATH,
        Icon,
        domain_from_website,
        fund_family_domain,
        icon_url,
        icons_for_names,
        institution_icons,
        payee_icons_by_name,
    )
    from app.services.finance.domains.ledger.merchants import list_merchants
    from app.services.finance.domains.ledger.net_worth_rule import (
        assets_and_owed,
        counts_in_net_worth,
        net_of,
    )
    from app.services.finance.domains.ledger.networth import recompute_snapshots
    from app.services.finance.domains.ledger.numbers import (
        aba_ok,
        reveal_number,
        set_last_four,
        set_number,
    )
    from app.services.finance.domains.ledger.packet import receipts_packet
    from app.services.finance.domains.ledger.properties import (
        PROPERTY_ACCOUNT_TYPE,
        PROPERTY_KINDS,
        VALUATION_SOURCES,
        property_metadata,
        secured_position,
    )
    from app.services.finance.domains.ledger.queries import (
        account_ids_for_connection,
        transactions_by_ids,
    )
    from app.services.finance.domains.ledger.queries.accounts import (
        EVERYONE,
        HOUSEHOLD,
        account_by_id,
        account_names,
        accounts_page,
        institution_by_id,
        recent_transaction_dates,
    )
    from app.services.finance.domains.ledger.queries.categories import (
        category_names_by_id,
    )
    from app.services.finance.domains.ledger.queries.filters import AXES, not_duplicate
    from app.services.finance.domains.ledger.queries.merchants import (
        merchants_by_ids,
        merchants_for_owner,
    )
    from app.services.finance.domains.ledger.queries.networth import (
        live_accounts_for_owner,
    )
    from app.services.finance.domains.ledger.queries.transactions import (
        newest_transaction_date,
    )
    from app.services.finance.domains.ledger.series_parsing import parse_series_lines
    from app.services.finance.domains.ledger.subjects import (
        get_subject,
        institution_for_party,
        institution_of,
        subject_filter,
        subject_for_party,
        subject_of,
    )
    from app.services.finance.domains.ledger.transactions import transaction_tags
    from app.services.finance.domains.ledger.valuations import (
        list_valuations,
        preferred_valuation_row,
    )
    from app.services.finance.domains.planning import budgets as planning_budgets
    from app.services.finance.domains.planning import plan as plans
    from app.services.finance.domains.planning import queries as planning_queries
    from app.services.finance.domains.planning.allocation import (
        MonthlyFigures,
        resolved_meta,
        target_for_rule,
    )
    from app.services.finance.domains.planning.budgets import strip
    from app.services.finance.domains.planning.budgets.closing import ClosedMonth
    from app.services.finance.domains.planning.debts import METHODS as PAYOFF_METHODS
    from app.services.finance.domains.planning.debts import Debt, amortize, extra_buys
    from app.services.finance.domains.planning.debts import plan as payoff_plan
    from app.services.finance.domains.planning.envelope_tags import tag_name
    from app.services.finance.domains.planning.envelopes import envelope_metadata
    from app.services.finance.domains.planning.goals import (
        GOAL_ACCOUNT_TYPE,
        goal_auto_contribute,
        goal_balance,
        goal_eta,
        goal_landing,
        goal_metadata,
        goal_progress,
        set_auto_contribute,
        set_goal_metadata,
    )
    from app.services.finance.domains.planning.insights import resolve_insight
    from app.services.finance.domains.planning.plan import plan_row
    from app.services.finance.domains.planning.recurring import (
        queries as recurring_queries,
    )
    from app.services.finance.domains.planning.recurring import streams
    from app.services.finance.domains.planning.recurring.forecast import (
        bill_reminder,
        upcoming_outflows,
    )
    from app.services.finance.domains.planning.recurring.review import (
        hydrate_streams,
        needs_review,
        past_due,
        review_queue,
    )
    from app.services.finance.domains.planning.recurring.statements import (
        record_statement,
    )
    from app.services.finance.domains.planning.recurring.upcoming import (
        Total,
        scheduled_by_account,
        totalled,
    )
    from app.services.finance.domains.planning.retirement import (
        LABELS as PLAN_TYPE_LABELS,
    )
    from app.services.finance.domains.planning.retirement import TYPES as PLAN_TYPES
    from app.services.finance.domains.planning.retirement import Assumptions
    from app.services.finance.domains.planning.retirement import label as plan_label
    from app.services.finance.domains.writes.curation import (
        AssignPayeePayload,
        assign_payee_execute,
    )
    from app.services.finance.domains.writes.display import txn_row
    from app.services.finance.domains.writes.terms import (
        EXTRA_PAYMENT,
        PREPAYMENT,
        LoanTermsPayload,
        loan_terms_execute,
        shape_for,
        shown,
        typed,
    )
    from app.services.finance.models import (
        FinanceAccount,
        FinanceCategory,
        FinanceConnection,
        FinanceInsight,
        FinancePlan,
        FinanceRecurringStream,
        FinanceSubject,
        FinanceTag,
        FinanceTransaction,
        FinanceTransactionChangelog,
        FinanceTransactionSplit,
    )
    from app.services.finance.models.accounts import (
        FinanceLiabilityDetail,
        FinanceValuation,
    )
    from app.services.finance.models.imports import FinanceImportBatch
    from app.services.finance.models.planning import INSIGHT_RESOLUTIONS
    from app.services.finance.service.finance_service import FinanceService

__getattr__, __all__ = facade.lazy(__name__, __file__)
