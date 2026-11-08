"""The plan runs to retirement, on the ledger (#351-#354): the balances
on file sorted into the plan's types, the stated assumptions kept and
read back, a pension declared as income from its start date, and the
quarterly check that files an Attention item against the saved path.
"""

from datetime import date

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance import jobs
from app.services.finance.domains.detection.insights.rules.plan import plan_check
from app.services.finance.domains.planning import plan as plans
from app.services.finance.domains.planning.retirement import DEFAULT_RETURNS
from app.services.finance.models import FinancePlan
from app.services.finance.service import FinanceService
from tests.services._finance_factories import (
    seed_account,
    seed_household,
    seed_loan,
    seed_stream,
)
from tests.services.test_finance_insights import _insights_of

TODAY = date(2026, 11, 8)


async def _household(svc: FinanceService, db: AsyncSession) -> None:
    await seed_household(svc, db)
    await seed_loan(svc, db, "Car loan")


class TestWhatThePlanStartsFrom:
    @pytest.mark.asyncio
    async def test_balances_fall_into_the_plans_types(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await _household(svc, async_db_session)
        await seed_stream(
            svc,
            name="Monthly transfer",
            direction="inflow",
            expected_amount=50_000,
            next_expected_date=TODAY,
            account_id=(await _account(svc, "Brokerage")).id,
        )

        inputs = await plans.plan_inputs(async_db_session, owner_user_id=1, today=TODAY)

        assert inputs.balances == {
            "cash": 1_000_000,
            "investments": 10_000_000,
            "property": 40_000_000,
        }
        assert [d.name for d in inputs.debts] == ["Car loan"]
        # What goes into investments each month, measured off the streams
        # that land in them.
        assert inputs.measured_contributions == {"investments": 50_000}

    @pytest.mark.asyncio
    async def test_someone_elses_money_and_hidden_accounts_stay_out(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_account(svc, "Checking", current_balance=1_000_000)
        hidden = await seed_account(svc, "Hidden", current_balance=5_000_000)
        hidden.is_hidden = True
        async_db_session.add(hidden)
        await async_db_session.flush()

        inputs = await plans.plan_inputs(async_db_session, owner_user_id=1, today=TODAY)

        assert inputs.balances["cash"] == 1_000_000


@pytest.mark.queryspy(threshold=3)  # the plan saved, then read back
class TestAssumptionsAreKept:
    @pytest.mark.asyncio
    async def test_the_defaults_before_anything_is_stated(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        stated = (
            await plans.run_plan(async_db_session, owner_user_id=1, today=TODAY, runs=1)
        ).assumptions

        assert stated.birth_year is None
        assert stated.retire_age == 67 and stated.end_age == 95
        assert stated.rate("investments") == DEFAULT_RETURNS["investments"]

    @pytest.mark.asyncio
    async def test_saving_keeps_them_and_draws_the_path(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await _household(svc, async_db_session)

        saved = await plans.save_plan(
            async_db_session,
            owner_user_id=1,
            today=TODAY,
            birth_year=1966,
            retire_age=65,
            end_age=90,
            returns={"cash": 100, "investments": 500, "property": 200},
            volatility={"cash": 0, "investments": 1_200, "property": 300},
            contributions={"investments": 100_000},
            spending=400_000,
        )
        stated = (
            await plans.run_plan(async_db_session, owner_user_id=1, today=TODAY, runs=1)
        ).assumptions

        assert stated.birth_year == 1966 and stated.retire_age == 65
        assert stated.rate("investments") == 500
        assert stated.contribution("investments") == 100_000
        assert stated.spending == 400_000
        # The path starts at today's net worth and runs to the end age.
        row = saved.row
        assert row is not None
        assert row.path[0] == [TODAY.isoformat(), 51_000_000 - 100_000]
        assert row.path[-1][0] == "2056-11-08"
        assert row.path_saved_on == TODAY
        assert saved.path.start.net == 51_000_000 - 100_000

    @pytest.mark.asyncio
    async def test_saving_again_replaces_not_duplicates(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        for age in (65, 70):
            await plans.save_plan(
                async_db_session, owner_user_id=1, today=TODAY, retire_age=age
            )

        rows = (await async_db_session.exec(select(FinancePlan))).all()
        assert len(rows) == 1 and rows[0].retire_age == 70


class TestRetirementIncome:
    @pytest.mark.asyncio
    async def test_a_pension_becomes_an_income_stream_from_its_start(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        stream = await plans.declare_income(
            async_db_session,
            owner_user_id=1,
            name="State pension",
            kind="pension",
            monthly=200_000,
            starts=date(2031, 3, 1),
        )

        assert stream.direction == "inflow" and stream.frequency == "monthly"
        assert stream.next_expected_date == date(2031, 3, 1)
        assert stream.source == "user" and stream.is_user_confirmed
        ran = await plans.run_plan(
            async_db_session, owner_user_id=1, today=TODAY, runs=1
        )
        assert [(i.name, i.monthly, i.starts, i.kind) for i in ran.inputs.incomes] == [
            ("State pension", 200_000, date(2031, 3, 1), "pension")
        ]

    @pytest.mark.asyncio
    async def test_an_unknown_kind_is_refused(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        with pytest.raises(ValueError):
            await plans.declare_income(
                async_db_session,
                owner_user_id=1,
                name="Lottery",
                kind="windfall",
                monthly=1,
                starts=TODAY,
            )

    @pytest.mark.asyncio
    async def test_ordinary_income_is_not_retirement_income(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_stream(
            svc,
            name="Payroll",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=TODAY,
        )

        ran = await plans.run_plan(
            async_db_session, owner_user_id=1, today=TODAY, runs=1
        )
        assert ran.inputs.incomes == []


@pytest.mark.queryspy(threshold=3)  # the plan saved, then run
class TestThePlanRuns:
    @pytest.mark.asyncio
    async def test_the_outcome_carries_the_line_the_band_and_the_inputs(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await _household(svc, async_db_session)
        await plans.save_plan(
            async_db_session,
            owner_user_id=1,
            today=TODAY,
            birth_year=1966,
            retire_age=65,
            end_age=70,
            spending=300_000,
        )

        outcome = await plans.run_plan(
            async_db_session, owner_user_id=1, today=TODAY, runs=20
        )

        assert outcome.path.start.net == 51_000_000 - 100_000
        assert outcome.band.runs == 20 and len(outcome.band.years) == 10
        assert outcome.band.years == tuple(y.year for y in outcome.path.years)
        assert outcome.assumptions.spending == 300_000


@pytest.mark.queryspy(threshold=5)  # the plan saved, then checked each night
class TestThePlanChecksItself:
    async def _saved(self, svc: FinanceService, db: AsyncSession) -> None:
        await seed_household(svc, db)
        await plans.save_plan(
            db,
            owner_user_id=1,
            today=date(2026, 1, 1),
            birth_year=1966,
            returns={"cash": 0, "investments": 0, "property": 0},
            contributions={"investments": 100_000},
        )

    @pytest.mark.asyncio
    async def test_the_quarter_opens_with_a_check_against_the_path(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await self._saved(svc, async_db_session)

        await plan_check(async_db_session, 1, date(2027, 1, 1))

        rows = await _insights_of(async_db_session, "plan_check")
        assert len(rows) == 1
        # The path expected $12,000 of contributions in its first year and
        # the balances have not moved: behind by that much.
        assert rows[0].severity == "warning"
        assert rows[0].title == "Behind the plan by $12,000.00"
        assert "$510,000.00 against $522,000.00" in (rows[0].body or "")
        assert rows[0].dedup_key == "plan_check:2027Q1"
        assert rows[0].detected_amount == -1_200_000

    @pytest.mark.asyncio
    async def test_on_track_is_said_quietly(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await self._saved(svc, async_db_session)

        await plan_check(async_db_session, 1, date(2026, 1, 5))

        rows = await _insights_of(async_db_session, "plan_check")
        assert len(rows) == 1
        assert rows[0].severity == "info"
        assert rows[0].title == "The plan is on track"

    @pytest.mark.asyncio
    async def test_once_a_quarter_and_never_without_a_saved_plan(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_account(svc, "Checking", current_balance=1_000_000)
        assert await plan_check(async_db_session, 1, TODAY) == 0
        assert await _insights_of(async_db_session, "plan_check") == []

        await self._saved(svc, async_db_session)
        assert await plan_check(async_db_session, 1, date(2027, 4, 1)) == 1
        assert await plan_check(async_db_session, 1, date(2027, 5, 1)) == 0
        assert len(await _insights_of(async_db_session, "plan_check")) == 1

    @pytest.mark.asyncio
    async def test_the_quarterly_job_walks_every_owner(
        self,
        svc: FinanceService,
        async_db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _session():  # noqa: ANN202
            yield async_db_session

        monkeypatch.setattr(jobs, "get_async_session", _session)
        await self._saved(svc, async_db_session)

        await jobs.finance_plan_check_job()

        assert len(await _insights_of(async_db_session, "plan_check")) == 1


async def _account(svc: FinanceService, name: str):
    accounts, _ = await svc.list_accounts(owner_user_id=1, page_size=50)
    return next(a for a in accounts if a.name == name)
