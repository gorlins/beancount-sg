"""Tests for the Year in Review's calculations (see test_year_end.py for the page)."""

import datetime
from decimal import Decimal

import pytest
from beancount.core import prices
from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES
from beancount.core.data import Open

from beancount_sg.cash_flow_roles import CASH, account_roles
from beancount_sg.ext.year_end.metrics import (
    DEBT,
    INVESTMENTS,
    OTHER,
    PROPERTY,
    RETURNS,
    TRANSFERS,
    Debt,
    YearSummary,
    classify,
    year_end,
    years_shown,
)
from beancount_sg.testing import load

LEDGER = """
option "operating_currency" "USD"

2020-01-01 open Assets:Bank:Checking USD
2020-01-01 open Assets:Brokerage
2020-01-01 open Assets:Home USD
  investable: FALSE
2020-01-01 open Liabilities:CreditCard USD
2020-01-01 open Liabilities:Home:Mortgage USD
2020-01-01 open Equity:Opening
2020-01-01 open Income:Salary USD
2020-01-01 open Expenses:Food:Groceries USD
2020-01-01 open Expenses:Housing:Interest USD

2023-01-01 * "Opening balances"
  Assets:Bank:Checking  10000 USD
  Assets:Home  300000 USD
  Liabilities:Home:Mortgage  -200000 USD
  Equity:Opening

2024-01-31 * "Salary"
  Assets:Bank:Checking  100000 USD
  Income:Salary

2024-02-01 * "Groceries"
  Expenses:Food:Groceries  5000 USD
  Assets:Bank:Checking

2024-02-02 * "Groceries on the card"
  Expenses:Food:Groceries  1000 USD
  Liabilities:CreditCard

2024-03-01 * "Mortgage payment"
  Liabilities:Home:Mortgage  10000 USD
  Expenses:Housing:Interest  2000 USD
  Assets:Bank:Checking

2024-04-01 * "Buy VTI"
  Assets:Brokerage  10 VTI {200 USD}
  Assets:Bank:Checking

2024-12-31 price VTI  250 USD
"""


def classes(ledger=LEDGER):
    entries, _ = load(ledger)
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    opens = [entry for entry in entries if isinstance(entry, Open)]
    return entries, classify(opens, roles, DEFAULT_ACCOUNT_TYPES)


def summaries(ledger=LEDGER, years=(2024,), today=datetime.date(2030, 1, 1)):
    entries, found = classes(ledger)
    price_map = prices.build_price_map(entries)
    result = year_end(entries, price_map, found, DEFAULT_ACCOUNT_TYPES, "USD", list(years), today)
    return {summary.year: summary for summary in result.years}, result


def test_classification():
    _, found = classes()
    assert {account: c.group for account, c in found.items()} == {
        "Assets:Bank:Checking": CASH,
        "Assets:Brokerage": INVESTMENTS,
        "Assets:Home": PROPERTY,
        "Liabilities:CreditCard": DEBT,  # financing, by default, like a loan
        "Liabilities:Home:Mortgage": DEBT,
    }
    assert found["Assets:Home"].reason == "investable: False on Assets:Home"
    assert found["Liabilities:CreditCard"].reason == "financing, by default"


def test_investable_metadata():
    ledger = LEDGER.replace("investable: FALSE", "investable: TRUE").replace(
        "2020-01-01 open Assets:Brokerage", "2020-01-01 open Assets:Brokerage\n  investable: FALSE"
    )
    _, found = classes(ledger)
    assert found["Assets:Home"].group == INVESTMENTS
    assert found["Assets:Brokerage"].group == PROPERTY
    assert found["Assets:Brokerage"].reason == "investable: False on Assets:Brokerage"


def test_a_secured_loan_does_not_make_property():
    # A margin loan under the brokerage's path: the brokerage is still investable.
    _, found = classes(LEDGER + "2020-01-01 open Liabilities:Brokerage:Margin USD\n")
    assert found["Assets:Brokerage"].group == INVESTMENTS
    assert found["Liabilities:Brokerage:Margin"].group == DEBT


def test_investable_inheritance_does_not_depend_on_open_order():
    ledger = (
        LEDGER
        + """
2019-01-01 open Assets:Vehicles:Car USD
2021-01-01 open Assets:Vehicles
  investable: FALSE
"""
    )
    _, found = classes(ledger)
    assert found["Assets:Vehicles:Car"].group == PROPERTY
    assert found["Assets:Vehicles:Car"].reason == "investable: False on Assets:Vehicles"


def test_a_liability_with_another_role_is_other():
    ledger = LEDGER.replace(
        "2020-01-01 open Liabilities:CreditCard USD",
        '2020-01-01 open Liabilities:CreditCard USD\n  cash-flow-role: "operating"',
    )
    _, found = classes(ledger)
    assert found["Liabilities:CreditCard"].group == OTHER


def test_net_worth_by_group_at_market_value():
    [summary] = summaries()[0].values()
    assert summary.net_worth_start == 110000
    assert summary.holdings == {
        CASH: 91000,
        INVESTMENTS: 2500,  # VTI at 250
        PROPERTY: 300000,
        DEBT: -191000,  # the mortgage and the card
        OTHER: 0,
    }
    assert summary.net_worth == 202500
    assert summary.net_worth_change == 92500
    assert summary.investable == 93500


def test_income_spending_and_savings():
    [summary] = summaries()[0].values()
    assert (summary.income, summary.expenses, summary.savings) == (100000, 8000, 92000)
    assert summary.savings_rate == 92
    assert summary.top_categories == [("Expenses:Food", 6000), ("Expenses:Housing", 2000)]


def test_spending_ratios():
    [summary] = summaries()[0].values()
    # A whole year's 12 months are the year: its spending against balances at its end.
    assert summary.trailing_start == datetime.date(2024, 1, 1)
    assert summary.trailing_expenses == summary.expenses == 8000
    assert summary.spending_rate == Decimal(100 * 8000) / 202500
    assert summary.withdrawal_rate == Decimal(100 * 8000) / 93500
    assert summary.months_of_cash == Decimal(12 * 91000) / 8000


def test_debt_paid_down_is_the_fall_in_balances():
    [summary] = summaries()[0].values()
    assert summary.debts == [
        Debt("Liabilities:CreditCard", start=0, end=1000),
        Debt("Liabilities:Home:Mortgage", start=200000, end=190000),
    ]
    assert [debt.paid_down for debt in summary.debts] == [-1000, 10000]
    assert summary.debt_paid_down == 9000


def test_a_card_paid_in_full_nets_to_zero():
    ledger = (
        LEDGER
        + """
2024-02-25 * "Card payment"
  Liabilities:CreditCard  1000 USD
  Assets:Bank:Checking
"""
    )
    [summary] = summaries(ledger)[0].values()
    assert Debt("Liabilities:CreditCard", start=0, end=0) not in summary.debts  # no balance
    assert summary.debt_paid_down == 10000


def test_new_borrowing():
    ledger = (
        LEDGER
        + """
2020-01-01 open Liabilities:CarLoan USD
2024-06-01 * "Car loan"
  Assets:Bank:Checking  20000 USD
  Liabilities:CarLoan
"""
    )
    [summary] = summaries(ledger)[0].values()
    assert Debt("Liabilities:CarLoan", start=0, end=20000) in summary.debts
    assert summary.debt_paid_down == 10000 - 1000 - 20000


def test_consecutive_years_chain():
    found, _ = summaries(years=(2023, 2024))
    assert found[2023].net_worth_start == 0
    assert found[2023].net_worth == 110000 == found[2024].net_worth_start
    assert found[2023].spending_rate == 0  # no spending
    assert found[2023].months_of_cash is None
    assert found[2023].savings_rate is None  # no income


def test_year_to_date_spending_ratios_use_the_last_12_months():
    ledger = (
        LEDGER
        + """
2023-09-01 * "Groceries last year"
  Expenses:Food:Groceries  1200 USD
  Assets:Bank:Checking
"""
    )
    found, _ = summaries(ledger, today=datetime.date(2024, 7, 1))
    summary = found[2024]
    assert not summary.complete
    assert summary.end == datetime.date(2024, 7, 2)
    # Flows are the year so far; the ratios' spending is the last 12 months'.
    assert summary.expenses == 8000
    assert summary.trailing_start == datetime.date(2023, 7, 2)
    assert summary.trailing_expenses == 9200
    # Balances are today's. VTI's only price, on 2024-12-31, is after today: it's at cost.
    assert summary.holdings[INVESTMENTS] == 2000
    assert summary.withdrawal_rate == Decimal(100 * 9200) / summary.investable


def test_the_12_months_before_february_29th():
    summary = YearSummary(2028, datetime.date(2028, 2, 29))
    assert summary.trailing_start == datetime.date(2027, 2, 28)


def test_unconverted_currencies_are_reported():
    ledger = (
        LEDGER
        + """
2024-05-01 * "Euros, without an exchange rate"
  Assets:Brokerage  100 EUR
  Equity:Opening
"""
    )
    found, result = summaries(ledger)
    assert result.unconverted == {"EUR"}
    assert found[2024].holdings[INVESTMENTS] == 2500


@pytest.mark.parametrize(
    ("first", "start", "end", "expected"),
    [
        (2018, None, 2025, [2021, 2022, 2023, 2024, 2025]),  # a year: it and four before
        (2024, None, 2025, [2024, 2025]),  # none before the first year
        (2018, 2023, 2024, [2023, 2024]),  # a range of years
        (2010, 2015, 2025, [2021, 2022, 2023, 2024, 2025]),  # at most five, the latest
    ],
)
def test_years_shown(first, start, end, expected):
    assert years_shown(first, start, end) == expected


ROLLOVER = """
2020-01-01 open Assets:Retirement:OldPlan
2020-01-01 open Assets:Retirement:NewPlan
2020-01-01 open Income:Retirement:Gains USD
  cash-flow-role: "investing"
2020-01-01 open Expenses:Retirement:Fees USD
  cash-flow-role: "investing"

2023-06-01 * "Old plan"
  Assets:Retirement:OldPlan  100 VTI {100 USD}
  Equity:Opening

2024-06-01 * "Rollover: sell in the old plan"
  Assets:Retirement:OldPlan  -100 VTI {100 USD} @ 400 USD
  Assets:Retirement:OldPlan  40000 USD
  Income:Retirement:Gains

2024-06-02 * "Rollover: buy in the new plan, less a fee"
  Assets:Retirement:OldPlan  -40000 USD
  Assets:Retirement:NewPlan  99 VXUS {400 USD}
  Expenses:Retirement:Fees  400 USD
"""


def test_investment_returns_are_classified():
    _, found = classes(LEDGER + ROLLOVER)
    assert found["Income:Retirement:Gains"].group == RETURNS
    assert found["Income:Retirement:Gains"].reason == (
        "investing, declared on Income:Retirement:Gains"
    )
    assert found["Expenses:Retirement:Fees"].group == RETURNS
    assert "Income:Salary" not in found  # operating, by default: income


def test_investment_returns_are_not_income_or_expenses():
    [summary] = summaries(LEDGER + ROLLOVER)[0].values()
    # The same income, spending and savings as without the rollover.
    assert (summary.income, summary.expenses, summary.savings) == (100000, 8000, 92000)
    assert summary.trailing_expenses == 8000
    assert "Expenses:Retirement" not in summary.expenses_by_category
    # The gain, less the fee.
    assert summary.investment_returns == 30000 - 400


def test_transfers_are_neither_expenses_nor_returns():
    # A loan payment passes through an expense account, reaching the loan next year.
    ledger = (
        LEDGER
        + """
2020-01-01 open Expenses:LoanRepayment USD
  cash-flow-role: "financing"

2024-12-30 * "Mortgage payment"
  Expenses:LoanRepayment  1000 USD
  Assets:Bank:Checking

2025-01-03 * "Mortgage payment applied"
  Liabilities:Home:Mortgage  1000 USD
  Expenses:LoanRepayment
"""
    )
    _, found = classes(ledger)
    assert found["Expenses:LoanRepayment"].group == TRANSFERS
    found_years, _ = summaries(ledger, years=(2024, 2025))
    for summary in found_years.values():
        assert summary.investment_returns == 0
    assert found_years[2024].expenses == 8000  # not the payment
    assert found_years[2025].expenses == 0
    # The loan counts it, when it arrives.
    assert found_years[2025].debt_paid_down == 1000
