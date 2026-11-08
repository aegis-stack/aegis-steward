"""Debts that pay down (#347-#350): the terms on file become a schedule,
an extra payment is priced before it is paid, a pay-down goal asks only
for the extra, and the debts line up in payoff order.

Hand-checked loan: $1,000 at 12% (1% a month) paid $100 a month.
Month by month the interest is 1000, 910, 819, 727, 635, 541, 446, 351,
254, 157, 58 cents: eleven payments, $58.98 of interest in all.
"""

from datetime import date

from app.services.finance.constants import add_months
from app.services.finance.domains.planning import debts
from app.services.finance.domains.planning.debts import Debt

START = date(2026, 11, 1)


def _loan(**over: object) -> Debt:
    base: dict[str, object] = {
        "account_id": 1,
        "name": "Loan",
        "owed": 100_000,
        "rate_bps": 1_200,
        "payment": 10_000,
        "escrow": 0,
        "extra_treatment": "principal",
        "prepayment_penalty": "none",
    }
    return Debt(**(base | over))  # type: ignore[arg-type]


class TestTheTermsBecomeASchedule:
    def test_the_schedule_pays_the_loan_off(self) -> None:
        schedule = debts.amortize(_loan(), start=START)

        assert schedule is not None
        assert len(schedule.steps) == 11
        assert schedule.paid_off == add_months(START, 10)
        assert schedule.interest == 5_898
        assert schedule.steps[0].interest == 1_000
        assert schedule.steps[0].principal == 9_000
        assert schedule.steps[0].owed == 91_000
        assert schedule.steps[-1].owed == 0

    def test_escrow_is_not_paid_toward_the_loan(self) -> None:
        """A $100 payment with $20 of escrow pays $80 toward the loan."""
        plain = debts.amortize(_loan(payment=8_000), start=START)
        escrowed = debts.amortize(_loan(payment=10_000, escrow=2_000), start=START)

        assert plain is not None and escrowed is not None
        assert escrowed.steps == plain.steps

    def test_a_payment_that_does_not_cover_the_interest_never_ends(self) -> None:
        schedule = debts.amortize(_loan(payment=1_000), start=START)

        assert schedule is not None
        assert schedule.paid_off is None
        assert schedule.steps == ()

    def test_no_rate_or_no_payment_is_no_schedule(self) -> None:
        assert debts.amortize(_loan(rate_bps=None), start=START) is None
        assert debts.amortize(_loan(payment=None), start=START) is None

    def test_a_zero_rate_is_a_schedule(self) -> None:
        schedule = debts.amortize(_loan(rate_bps=0), start=START)

        assert schedule is not None
        assert len(schedule.steps) == 10
        assert schedule.interest == 0


class TestWhatAnExtraPaymentBuys:
    def test_fifty_more_a_month_saves_four_months_and_the_interest(self) -> None:
        saving = debts.extra_buys(_loan(), start=START, extra=5_000)

        assert saving is not None
        assert saving.months_sooner == 4
        assert saving.interest_saved == 1_886
        assert saving.applies

    def test_a_lump_sum_is_paid_with_the_first_payment(self) -> None:
        saving = debts.extra_buys(_loan(), start=START, lump=50_000)

        assert saving is not None
        assert saving.months_sooner > 0
        assert saving.interest_saved > 0

    def test_extra_that_only_pays_ahead_buys_nothing(self) -> None:
        """A lender that applies extra to future instalments saves the
        payer no interest: the schedule does not move."""
        saving = debts.extra_buys(
            _loan(extra_treatment="future_installments"), start=START, extra=5_000
        )

        assert saving is not None
        assert not saving.applies
        assert saving.months_sooner == 0
        assert saving.interest_saved == 0

    def test_unconfirmed_treatment_is_computed_but_says_so(self) -> None:
        saving = debts.extra_buys(_loan(extra_treatment=None), start=START, extra=5_000)

        assert saving is not None
        assert saving.applies
        assert saving.unconfirmed
        assert saving.interest_saved == 1_886

    def test_a_penalty_is_carried_on_the_answer(self) -> None:
        saving = debts.extra_buys(
            _loan(prepayment_penalty="penalty"), start=START, extra=5_000
        )

        assert saving is not None
        assert saving.penalty


class TestThePayDownGoal:
    def test_the_extra_to_finish_by_a_date(self) -> None:
        by = add_months(START, 6)
        extra = debts.extra_to_finish_by(_loan(), start=START, by=by)

        assert extra is not None
        assert 0 < extra <= 5_000
        done = debts.amortize(_loan(), start=START, extra=extra)
        assert done is not None and done.paid_off is not None
        assert done.paid_off <= by
        short = debts.amortize(_loan(), start=START, extra=extra - 100)
        assert short is not None and short.paid_off is not None
        assert short.paid_off > by

    def test_a_date_the_schedule_already_meets_asks_nothing_extra(self) -> None:
        assert (
            debts.extra_to_finish_by(_loan(), start=START, by=add_months(START, 12))
            == 0
        )

    def test_a_lender_that_pays_ahead_cannot_be_hurried(self) -> None:
        extra = debts.extra_to_finish_by(
            _loan(extra_treatment="future_installments"),
            start=START,
            by=add_months(START, 6),
        )

        assert extra is None


class TestDebtsInPayoffOrder:
    def _two(self) -> list[Debt]:
        return [
            _loan(
                account_id=1, name="Card", owed=100_000, rate_bps=1_200, payment=10_000
            ),
            _loan(account_id=2, name="Promo", owed=50_000, rate_bps=0, payment=5_000),
        ]

    def test_avalanche_puts_the_dearest_first_and_snowball_the_smallest(self) -> None:
        assert [d.name for d in debts.ordered(self._two(), "avalanche")] == [
            "Card",
            "Promo",
        ]
        assert [d.name for d in debts.ordered(self._two(), "snowball")] == [
            "Promo",
            "Card",
        ]

    def test_a_debt_with_no_rate_sorts_last_under_avalanche(self) -> None:
        unknown = _loan(account_id=3, name="Unknown", rate_bps=None)
        assert debts.ordered([unknown, *self._two()], "avalanche")[-1].name == "Unknown"

    def test_the_next_dollar_goes_to_the_first_and_a_paid_debt_rolls_on(self) -> None:
        plan = debts.plan(self._two(), "avalanche", start=START, extra=5_000)

        assert plan.next is not None and plan.next.name == "Card"
        by_name = {line.debt.name: line for line in plan.lines}
        # The card, with the extra, is done in seven payments (above); its
        # $150 then rolls onto the promo balance, which ends the same month
        # instead of three months later on its own.
        assert by_name["Card"].paid_off == add_months(START, 6)
        assert by_name["Promo"].paid_off == add_months(START, 7)
        assert plan.debt_free == add_months(START, 7)
        assert plan.interest == 4_012
        assert plan.alone_interest == 5_898
        assert plan.interest_saved == 1_886

    def test_snowball_pays_more_interest_here(self) -> None:
        plan = debts.plan(self._two(), "snowball", start=START, extra=5_000)

        assert plan.next is not None and plan.next.name == "Promo"
        assert plan.interest == 5_128
        assert plan.debt_free == add_months(START, 7)

    def test_a_debt_without_terms_is_listed_but_not_planned(self) -> None:
        unknown = _loan(account_id=3, name="Unknown", rate_bps=None)
        plan = debts.plan([*self._two(), unknown], "avalanche", start=START)

        assert [line.debt.name for line in plan.lines] == ["Card", "Promo"]
        assert [d.name for d in plan.unplanned] == ["Unknown"]

    def test_no_debts_is_an_empty_plan(self) -> None:
        plan = debts.plan([], "avalanche", start=START)

        assert plan.lines == ()
        assert plan.next is None
        assert plan.debt_free is None
