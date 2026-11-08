"""Debts that pay down, on the page (#347, #348, #350).

A loan's cover says when it ends and what the interest comes to, prices
an extra payment before it is paid, and marks what nobody confirmed. The
Paying down page lines every debt up by avalanche or snowball and says
where the next dollar goes.
"""

from datetime import date

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend.filters import money
from app.services.finance.constants import add_months
from app.services.finance.service import FinanceService
from app.services.finance.utils import current_date
from tests.services._finance_factories import seed_loan
from tests.web.conftest import Ledger
from tests.web.dom import card, none, one, select, stats, table_rows, text


class TestTheCoverSaysWhenItEnds:
    @pytest.mark.asyncio
    async def test_the_payoff_date_interest_and_payments_left(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        due = date(2027, 1, 15)
        loan = await seed_loan(finance, async_db_session, next_payment_due_date=due)

        page = hx.get(f"/accounts/{loan}/overview").text

        shown = stats(card(page, "Paying it down"))
        assert shown["Paid off"] == f"{add_months(due, 10):%b %Y}"
        assert shown["Interest left"] == money(5_898)
        assert shown["Payments left"] == "11"

    @pytest.mark.asyncio
    async def test_the_schedule_is_drawn_month_by_month(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(
            finance, async_db_session, next_payment_due_date=date(2027, 1, 15)
        )

        page = hx.get(f"/accounts/{loan}/overview").text

        rows = table_rows(card(page, "Paying it down"))
        assert len(rows) == 11
        assert text(rows[0]["Interest"]) == money(1_000)
        assert text(rows[0]["Principal"]) == money(9_000)
        assert text(rows[-1]["Owed"]) == money(0)

    @pytest.mark.asyncio
    async def test_a_payment_that_never_gets_there_says_so(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(finance, async_db_session, minimum_payment_amount=1_000)

        page = hx.get(f"/accounts/{loan}/overview").text

        shown = stats(card(page, "Paying it down"))
        assert shown["Paid off"] == "Never"
        none(card(page, "Paying it down"), "table")

    @pytest.mark.asyncio
    async def test_a_loan_with_no_rate_has_no_schedule(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(finance, async_db_session, interest_rate_bps=None)

        page = hx.get(f"/accounts/{loan}/overview").text

        paying = card(page, "Paying it down")
        assert "Paid off" not in stats(paying)
        one(paying, "[data-no-schedule]")

    @pytest.mark.asyncio
    async def test_both_render_paths(
        self,
        client: TestClient,
        hx: TestClient,
        finance: FinanceService,
        async_db_session: AsyncSession,
    ) -> None:
        loan = await seed_loan(finance, async_db_session)

        cold = client.get(f"/accounts/{loan}/overview").text
        swap = hx.get(f"/accounts/{loan}/overview").text

        one(cold, "html")
        none(swap, "html")
        assert stats(card(cold, "Paying it down")) == stats(
            card(swap, "Paying it down")
        )


class TestWhatAnExtraPaymentBuys:
    @pytest.mark.asyncio
    async def test_fifty_more_a_month_is_priced(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(finance, async_db_session)

        page = hx.get(f"/accounts/{loan}/overview?extra=50").text

        said = text(one(page, "[data-saving]"))
        assert "4 months sooner" in said
        assert money(1_886) in said
        # The strip and the schedule move with it.
        assert stats(card(page, "Paying it down"))["Payments left"] == "7"
        assert len(table_rows(card(page, "Paying it down"))) == 7

    @pytest.mark.asyncio
    async def test_a_lump_sum_is_priced_too(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(finance, async_db_session)

        page = hx.get(f"/accounts/{loan}/overview?lump=500").text

        assert "sooner" in text(one(page, "[data-saving]"))

    @pytest.mark.asyncio
    async def test_extra_that_only_pays_ahead_buys_nothing(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(
            finance, async_db_session, extra_payment_treatment="future_installments"
        )

        page = hx.get(f"/accounts/{loan}/overview?extra=50").text

        saving = one(page, "[data-saving]")
        assert saving.get("data-saving") == "none"
        assert stats(card(page, "Paying it down"))["Payments left"] == "11"

    @pytest.mark.asyncio
    async def test_unconfirmed_terms_stay_marked_unconfirmed(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(
            finance,
            async_db_session,
            extra_payment_treatment=None,
            prepayment_penalty=None,
        )

        page = hx.get(f"/accounts/{loan}/overview?extra=50").text

        one(page, "[data-saving][data-unconfirmed]")

    @pytest.mark.asyncio
    async def test_a_penalty_is_said_beside_the_saving(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(finance, async_db_session, prepayment_penalty="penalty")

        page = hx.get(f"/accounts/{loan}/overview?extra=50").text

        one(page, "[data-saving][data-penalty]")

    @pytest.mark.asyncio
    async def test_nonsense_is_ignored_not_a_crash(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        loan = await seed_loan(finance, async_db_session)

        page = hx.get(f"/accounts/{loan}/overview?extra=lots").text

        none(page, "[data-saving]")
        assert stats(card(page, "Paying it down"))["Payments left"] == "11"


class TestDebtsInPayoffOrder:
    async def _two(self, finance: FinanceService, db: AsyncSession) -> tuple[int, int]:
        card_id = await seed_loan(
            finance,
            db,
            "Store card",
            outstanding_balance=100_000,
            interest_rate_bps=1_200,
            minimum_payment_amount=10_000,
        )
        promo = await seed_loan(
            finance,
            db,
            "Promo loan",
            outstanding_balance=50_000,
            interest_rate_bps=0,
            minimum_payment_amount=5_000,
        )
        return card_id, promo

    @pytest.mark.asyncio
    async def test_avalanche_by_default_and_the_next_dollar(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await self._two(finance, async_db_session)

        page = hx.get("/accounts/payoff").text

        rows = table_rows(page)
        assert [text(r["Debt"]) for r in rows] == ["Store card", "Promo loan"]
        assert "Store card" in text(one(page, "[data-next-dollar]"))

    @pytest.mark.asyncio
    async def test_snowball_reorders(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await self._two(finance, async_db_session)

        page = hx.get("/accounts/payoff?method=snowball").text

        rows = table_rows(page)
        assert [text(r["Debt"]) for r in rows] == ["Promo loan", "Store card"]
        assert "Promo loan" in text(one(page, "[data-next-dollar]"))

    @pytest.mark.asyncio
    async def test_the_extra_rolls_a_paid_debt_onto_the_next(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await self._two(finance, async_db_session)
        today = current_date()

        page = hx.get("/accounts/payoff?extra=50").text

        shown = stats(page)
        assert shown["Debt-free"] == f"{add_months(today, 7):%b %Y}"
        assert shown["Interest"] == money(4_012)
        assert shown["Saved"] == money(1_886)
        rows = {text(r["Debt"]): r for r in table_rows(page)}
        assert text(rows["Promo loan"]["Paid off"]) == f"{add_months(today, 7):%b %Y}"

    @pytest.mark.asyncio
    async def test_a_debt_without_terms_is_listed_apart(
        self,
        hx: TestClient,
        finance: FinanceService,
        async_db_session: AsyncSession,
        ledger: Ledger,
    ) -> None:
        """The seeded Visa owes $25 and has no terms: it is named, with
        the door to its terms, not silently left out of the plan."""
        await self._two(finance, async_db_session)

        page = hx.get("/accounts/payoff").text

        assert [text(r["Debt"]) for r in table_rows(page)] == [
            "Store card",
            "Promo loan",
        ]
        assert text(one(page, "[data-unplanned]")).startswith("Visa")

    @pytest.mark.asyncio
    async def test_no_debts_is_an_empty_state(self, hx: TestClient) -> None:
        page = hx.get("/accounts/payoff").text

        one(page, "[data-empty]")
        none(page, "table")

    @pytest.mark.asyncio
    async def test_both_render_paths(
        self,
        client: TestClient,
        hx: TestClient,
        finance: FinanceService,
        async_db_session: AsyncSession,
    ) -> None:
        await self._two(finance, async_db_session)

        one(client.get("/accounts/payoff").text, "html")
        none(hx.get("/accounts/payoff").text, "html")

    @pytest.mark.asyncio
    async def test_the_portfolio_opens_the_door(
        self, hx: TestClient, ledger: Ledger
    ) -> None:
        page = hx.get("/accounts").text

        assert select(page, 'a[href="/accounts/payoff"]')
