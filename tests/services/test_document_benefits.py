"""Pension and Social Security become income at their start age (#352):
the benefit a filed statement estimates, read off the line that prints
it, becomes a proposed income stream from the day it starts.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.domains.reading.benefits import benefits
from app.services.documents.domains.reading.proposals import propose_reading
from app.services.finance.domains.planning import plan as plans
from app.services.finance.domains.writes.queue import list_changes
from tests._session import opens
from tests.services._document_factories import pages, seed_paper


class TestWhatAStatementSaysItWillPay:
    def test_social_security_names_an_age(self) -> None:
        found = benefits(
            pages(
                "SOCIAL SECURITY ADMINISTRATION",
                "Your Social Security Statement",
                "Your estimated monthly benefit at age 67 is $2,450.00",
            )
        )

        assert found is not None
        assert found.monthly_cents == 245_000
        assert found.kind == "social_security"
        assert found.start_age == 67 and found.starts is None

    def test_a_pension_names_a_date(self) -> None:
        found = benefits(
            pages("Monthly pension benefit beginning 03/01/2031: $1,800.00")
        )

        assert found is not None
        assert found.monthly_cents == 180_000
        assert found.kind == "pension"
        assert found.starts == date(2031, 3, 1) and found.start_age is None

    def test_the_labels_a_statement_prints(self) -> None:
        for line, cents in (
            ("Estimated monthly benefit: $2,100.00", 210_000),
            ("Monthly annuity amount $950.25", 95_025),
            ("Benefit amount (monthly) $1,200.00", 120_000),
        ):
            found = benefits(pages(line))
            assert found is not None and found.monthly_cents == cents, line

    def test_money_that_is_not_a_benefit(self) -> None:
        for line in (
            "Minimum payment due: $224.57",
            "Ending balance $3,137.44",
            "Your estimated monthly benefit at age 67 is",
        ):
            assert benefits(pages(line)) is None, line


@pytest.mark.queryspy(threshold=3)  # the plan saved or read twice, once per reading
class TestItReachesTheQueue:
    async def _declared(self, db: AsyncSession) -> list:
        return [
            c
            for c in await list_changes(db, status="pending")
            if c.change_type == "recurring.declare"
        ]

    @pytest.mark.asyncio
    async def test_an_age_becomes_a_start_date_from_the_plans_birth_year(
        self, async_db_session: AsyncSession
    ) -> None:
        await plans.save_plan(
            async_db_session,
            owner_user_id=None,
            today=date(2026, 11, 8),
            birth_year=1966,
        )
        document = await seed_paper(
            async_db_session,
            "SOCIAL SECURITY ADMINISTRATION",
            "Your estimated monthly benefit at age 67 is $2,450.00",
        )

        await propose_reading(opens(async_db_session), document.id)

        (card,) = await self._declared(async_db_session)
        assert card.payload["name"] == "Social Security"
        assert card.payload["direction"] == "inflow"
        assert card.payload["frequency"] == "monthly"
        assert card.payload["amount_cents"] == 245_000
        assert card.payload["next_expected_date"] == "2033-01-01"
        assert card.payload["income_kind"] == "social_security"
        assert card.payload["document_id"] == document.id
        assert card.proposed_by_agent == "reading"

    @pytest.mark.asyncio
    async def test_a_dated_pension_needs_no_plan(
        self, async_db_session: AsyncSession
    ) -> None:
        document = await seed_paper(
            async_db_session,
            "Monthly pension benefit beginning 03/01/2031: $1,800.00",
        )

        await propose_reading(opens(async_db_session), document.id)

        (card,) = await self._declared(async_db_session)
        assert card.payload["name"] == "Pension"
        assert card.payload["next_expected_date"] == "2031-03-01"
        assert card.payload["income_kind"] == "pension"

    @pytest.mark.asyncio
    async def test_no_start_anybody_can_name_proposes_nothing(
        self, async_db_session: AsyncSession
    ) -> None:
        document = await seed_paper(
            async_db_session, "Your estimated monthly benefit at age 67 is $2,450.00"
        )

        await propose_reading(opens(async_db_session), document.id)

        assert await self._declared(async_db_session) == []

    @pytest.mark.asyncio
    async def test_read_twice_asks_once(self, async_db_session: AsyncSession) -> None:
        document = await seed_paper(
            async_db_session, "Monthly pension benefit beginning 03/01/2031: $1,800.00"
        )

        await propose_reading(opens(async_db_session), document.id)
        await propose_reading(opens(async_db_session), document.id)

        assert len(await self._declared(async_db_session)) == 1

    @pytest.mark.asyncio
    async def test_approving_the_card_marks_the_income(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.writes.queue import approve

        document = await seed_paper(
            async_db_session, "Monthly pension benefit beginning 03/01/2031: $1,800.00"
        )
        await propose_reading(opens(async_db_session), document.id)
        (card,) = await self._declared(async_db_session)

        await approve(async_db_session, card.id)

        ran = await plans.run_plan(
            async_db_session, owner_user_id=None, today=date(2026, 11, 8), runs=1
        )
        incomes = ran.inputs.incomes
        assert [(i.name, i.monthly, i.starts, i.kind) for i in incomes] == [
            ("Pension", 180_000, date(2031, 3, 1), "pension")
        ]
