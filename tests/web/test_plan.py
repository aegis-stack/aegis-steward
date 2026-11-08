"""The plan runs to retirement, on the page (#351-#353).

Net worth by type walked to the end age, a band of simulated returns
around the line with the chance the plan holds, the assumptions shown
and editable in place, and a pension declared as income from its start.
"""

from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from app.services.finance.utils import current_date
from tests.services._finance_factories import seed_household
from tests.web.conftest import Ledger
from tests.web.dom import card, chart_data, none, one, select, stats, table_rows, text

PLAN = "/projected/plan"


def _save(client: TestClient, **over: str) -> Any:
    born = str(current_date().year - 60)
    fields = {
        "birth_year": born,
        "retire_age": "65",
        "end_age": "70",
        "return_cash": "0",
        "return_investments": "6",
        "return_property": "0",
        "swing_cash": "0",
        "swing_investments": "0",
        "swing_property": "0",
        "put_investments": "1,000",
        "spending": "3,000",
    } | over
    return client.post(PLAN, data=fields)


class TestNetWorthProjectsForward:
    @pytest.mark.queryspy(threshold=3)  # the save, then the page again
    @pytest.mark.asyncio
    async def test_the_strip_the_band_and_the_types(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_household(finance, async_db_session)
        assert _save(hx).status_code == 200

        page = hx.get(PLAN).text

        shown = stats(page)
        assert shown["Net worth today"] == "$510,000.00"
        # Four years of $12,000 at 6% on $100,000, then the retirement year
        # grows, stops contributing and draws $36,000: cash first. The
        # house sits at $400,000 throughout.
        assert shown["At retirement"] == "$563,467.68"
        assert "Chance it holds" in shown
        data = chart_data(page, "line")
        assert [s["label"] for s in data["series"]] == ["Low", "High", "Likely"]
        assert [s.get("band") for s in data["series"]] == ["low", "high", None]
        assert len(data["labels"]) == 10
        rows = {text(r["Type"]): r for r in table_rows(card(page, "By type"))}
        assert text(rows["Investments"]["Today"]) == "$100,000.00"
        assert text(rows["Cash"]["Today"]) == "$10,000.00"

    @pytest.mark.queryspy(threshold=3)  # the save, then the page again
    @pytest.mark.asyncio
    async def test_the_assumptions_are_shown_and_kept(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_household(finance, async_db_session)

        saved = _save(hx, return_investments="5.5")
        assert saved.status_code == 200
        page = hx.get(PLAN).text

        form = one(page, "form#assumptions")
        assert form.get("hx-post") == PLAN
        assert one(form, 'input[name="return_investments"]').get("value") == "5.5"
        assert one(form, 'input[name="retire_age"]').get("value") == "65"
        assert one(form, 'input[name="put_investments"]').get("value") == "1,000.00"
        assert one(form, 'input[name="spending"]').get("value") == "3,000.00"

    @pytest.mark.asyncio
    async def test_before_anything_is_stated_the_defaults_say_so(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_household(finance, async_db_session)

        page = hx.get(PLAN).text

        assert "At retirement" not in stats(page)
        one(page, "[data-unstated]")
        form = one(page, "form#assumptions")
        assert one(form, 'input[name="return_investments"]').get("value") == "6"

    @pytest.mark.asyncio
    async def test_nonsense_is_refused_with_the_form_back(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_household(finance, async_db_session)

        refused = _save(hx, birth_year="soon")

        assert refused.status_code == 422
        assert "Birth year" in text(one(refused.text, "[role=alert]"))

    @pytest.mark.queryspy(threshold=3)  # the page twice, cold and swapped
    @pytest.mark.asyncio
    async def test_both_render_paths(
        self,
        client: TestClient,
        hx: TestClient,
        finance: FinanceService,
        async_db_session: AsyncSession,
    ) -> None:
        await seed_household(finance, async_db_session)

        cold = client.get(PLAN).text
        swap = hx.get(PLAN).text

        one(cold, "html")
        none(swap, "html")
        assert stats(cold) == stats(swap)

    def test_projected_and_the_plan_are_tabs_of_one_section(
        self, client: TestClient, ledger: Ledger
    ) -> None:
        assert select(client.get("/projected").text, f'a[href="{PLAN}"]')
        assert select(client.get(PLAN).text, 'a[href="/projected"]')


class TestRetirementIncome:
    @pytest.mark.asyncio
    async def test_a_pension_is_declared_and_listed_from_its_start(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_household(finance, async_db_session)

        answer = hx.post(
            PLAN + "/income",
            data={
                "name": "State pension",
                "kind": "pension",
                "monthly": "2,000",
                "starts": "2031-03-01",
            },
        )

        assert answer.status_code == 200
        said = text(one(answer.text, "[data-income]"))
        assert "State pension" in said and "$2,000.00" in said and "Mar 2031" in said
        # It is a stream like any other: the Bills page lists it as income.
        assert "State pension" in hx.get("/bills?tab=income").text

    @pytest.mark.asyncio
    async def test_a_bad_amount_is_refused(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await seed_household(finance, async_db_session)

        answer = hx.post(
            PLAN + "/income",
            data={
                "name": "Pension",
                "kind": "pension",
                "monthly": "lots",
                "starts": "2031-03-01",
            },
        )

        assert answer.status_code == 422
        one(answer.text, "[role=alert]")


class TestThePlanChecksItself:
    @pytest.mark.queryspy(threshold=3)  # the plan saved, then checked
    @pytest.mark.asyncio
    async def test_the_quarters_check_opens_the_plan_from_attention(
        self, hx: TestClient, finance: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection.insights.rules.plan import (
            plan_check,
        )
        from app.services.finance.domains.planning import plan as plans

        await seed_household(finance, async_db_session)
        await plans.save_plan(
            async_db_session, owner_user_id=None, today=current_date(), birth_year=1966
        )
        await plan_check(async_db_session, None, current_date())
        await async_db_session.commit()

        page = hx.get("/review/attention").text

        item = one(page, "[data-open-plan]")
        assert item.get("hx-get") == PLAN
        assert "on track" in text(one(page, "#attention li")).lower()
