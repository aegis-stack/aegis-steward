"""The plan runs to retirement (#351-#354): net worth walked forward a
year at a time by account type, from the balances on file and stated
assumptions; pensions and Social Security arriving at their start date;
a band of simulated returns with a chance the plan holds; and the saved
path a quarter's actual figure is checked against.

Hand-checked plan: $10,000 cash at 0%, $100,000 invested at 6%, $1,000
a month put in until 65, $3,000 a month spent after. Born 1966, so 60
at the start, retired at 65, the plan ending at 70.
"""

from datetime import date

import pytest

from app.services.finance.domains.planning import retirement
from app.services.finance.domains.planning.debts import Debt
from app.services.finance.domains.planning.retirement import (
    Assumptions,
    Income,
    expected_on,
    project,
    simulate,
)

TODAY = date(2026, 11, 8)
BALANCES = {"cash": 1_000_000, "investments": 10_000_000, "property": 0}


def _plan(**over: object) -> Assumptions:
    base: dict[str, object] = {
        "birth_year": 1966,
        "retire_age": 65,
        "end_age": 70,
        "returns": {"cash": 0, "investments": 600, "property": 0},
        "volatility": {"cash": 0, "investments": 0, "property": 0},
        "contributions": {"cash": 0, "investments": 100_000, "property": 0},
        "spending": 300_000,
    }
    return Assumptions(**(base | over))  # type: ignore[arg-type]


class TestNetWorthProjectsForward:
    def test_each_type_grows_at_its_rate_and_takes_its_contributions(self) -> None:
        path = project(_plan(), BALANCES, [], [], today=TODAY)

        first = path.years[0]
        assert first.on == date(2027, 11, 8) and first.age == 61
        # 100,000 at 6% plus twelve $1,000 contributions.
        assert first.by_type["investments"] == 11_800_000
        assert first.by_type["cash"] == 1_000_000
        assert first.net == 12_800_000

    def test_the_plan_runs_to_the_end_age(self) -> None:
        path = project(_plan(), BALANCES, [], [], today=TODAY)

        assert [y.age for y in path.years] == [61, 62, 63, 64, 65, 66, 67, 68, 69, 70]
        assert path.at_retirement is not None and path.at_retirement.age == 65
        assert path.end.age == 70

    def test_retirement_stops_contributions_and_draws_cash_first(self) -> None:
        plan = _plan(birth_year=1962)  # 64 now: retired from the first year
        path = project(plan, BALANCES, [], [], today=TODAY)

        first = path.years[0]
        assert first.retired
        # $36,000 spent: the $10,000 of cash goes first, the rest is drawn
        # from investments after their year's growth.
        assert first.by_type["cash"] == 0
        assert first.by_type["investments"] == 10_600_000 - 2_600_000

    def test_income_that_has_started_offsets_the_spending(self) -> None:
        plan = _plan(birth_year=1962)
        pension = Income("Pension", 200_000, date(2027, 1, 1), "pension")
        later = Income("Social Security", 150_000, date(2028, 6, 1), "social_security")
        path = project(plan, BALANCES, [], [pension, later], today=TODAY)

        # Year one runs to 8 Nov 2027: eleven pension payments ($22,000)
        # against $36,000 spent, the $14,000 drawn cash first.
        assert path.years[0].by_type["cash"] == 0
        assert path.years[0].by_type["investments"] == 10_600_000 - 400_000
        # Year two: twelve pension payments and six of Social Security.
        year_two = path.years[1]
        drawn = 36_000_00 - 24_000_00 - 6 * 150_000
        assert year_two.by_type["investments"] == round(10_200_000 * 1.06) - drawn

    def test_a_surplus_in_retirement_lands_in_cash(self) -> None:
        plan = _plan(birth_year=1962, spending=100_000)
        pension = Income("Pension", 200_000, date(2020, 1, 1), "pension")
        path = project(plan, BALANCES, [], [pension], today=TODAY)

        assert path.years[0].by_type["cash"] == 1_000_000 + 12 * 100_000

    def test_debts_fall_away_as_their_schedules_say(self) -> None:
        loan = Debt(1, "Loan", 100_000, 1_200, 10_000, extra_treatment="principal")
        unplanned = Debt(2, "Card", 50_000, None, None)
        path = project(_plan(), BALANCES, [loan, unplanned], [], today=TODAY)

        # Eleven payments from this month: gone by the first anniversary.
        assert path.years[0].debts == 50_000
        assert path.years[0].net == 12_800_000 - 50_000
        assert path.start.debts == 150_000

    def test_without_a_birth_year_the_plan_runs_thirty_years_unretired(
        self,
    ) -> None:
        path = project(_plan(birth_year=None), BALANCES, [], [], today=TODAY)

        assert len(path.years) == 30
        assert path.at_retirement is None
        assert all(y.age is None and not y.retired for y in path.years)

    def test_the_type_an_account_falls_in(self) -> None:
        assert retirement.bucket("checking") == "cash"
        assert retirement.bucket("brokerage") == "investments"
        assert retirement.bucket("property") == "property"
        assert retirement.bucket("other_asset") == "property"


class TestARangeNotALine:
    def test_no_volatility_is_the_line_itself(self) -> None:
        path = project(_plan(), BALANCES, [], [], today=TODAY)
        band = simulate(_plan(), BALANCES, [], [], today=TODAY, runs=50)

        assert band.years == tuple(y.year for y in path.years)
        assert band.mid == tuple(y.net for y in path.years)
        assert band.low == band.mid == band.high
        assert band.success == 1.0
        assert band.runs == 50

    def test_volatility_opens_a_band_and_the_seed_fixes_it(self) -> None:
        plan = _plan(volatility={"cash": 0, "investments": 1_500, "property": 0})
        band = simulate(plan, BALANCES, [], [], today=TODAY, runs=200, seed=7)
        again = simulate(plan, BALANCES, [], [], today=TODAY, runs=200, seed=7)

        assert band == again
        assert band.low[-1] < band.mid[-1] < band.high[-1]
        assert 0.0 <= band.success <= 1.0

    def test_a_plan_that_cannot_hold_says_so(self) -> None:
        plan = _plan(birth_year=1962, spending=5_000_000)
        band = simulate(plan, BALANCES, [], [], today=TODAY, runs=20)

        assert band.success == 0.0
        assert band.mid[-1] < 0


class TestThePlanChecksItself:
    def test_expected_net_worth_is_read_between_the_path_points(self) -> None:
        path = project(_plan(), BALANCES, [], [], today=TODAY)
        saved = path.saved()

        assert saved[0] == [TODAY.isoformat(), 11_000_000]
        assert saved[1] == ["2027-11-08", 12_800_000]
        assert expected_on(saved, TODAY) == 11_000_000
        assert expected_on(saved, date(2027, 11, 8)) == 12_800_000
        # Halfway through the first stretch reads halfway up it.
        midway = TODAY + (date(2027, 11, 8) - TODAY) / 2
        assert expected_on(saved, midway) == pytest.approx(11_900_000, abs=3_000)
        # Past the end the path holds its last figure.
        assert expected_on(saved, date(2099, 1, 1)) == path.end.net
