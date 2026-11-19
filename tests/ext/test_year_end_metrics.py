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
    Debt,
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
        "Assets:Home": PROPERTY,  # it secures Liabilities:Home:Mortgage
        "Liabilities:CreditCard": OTHER,  # a card, by its name
        "Liabilities:Home:Mortgage": DEBT,
    }
    assert found["Assets:Home"].reason == "secures Liabilities:Home:Mortgage"
    assert found["Liabilities:CreditCard"].reason == "a credit card, by its name"


def test_investable_metadata_overrides_the_inference():
    ledger = LEDGER.replace(
        "2020-01-01 open Assets:Home USD", "2020-01-01 open Assets:Home USD\n  investable: TRUE"
    ).replace(
        "2020-01-01 open Assets:Brokerage", "2020-01-01 open Assets:Brokerage\n  investable: FALSE"
    )
    _, found = classes(ledger)
    assert found["Assets:Home"].group == INVESTMENTS
    assert found["Assets:Brokerage"].group == PROPERTY
    assert found["Assets:Brokerage"].reason == "investable: False on Assets:Brokerage"


def test_a_declared_financing_card_is_debt():
    ledger = LEDGER.replace(
        "2020-01-01 open Liabilities:CreditCard USD",
        '2020-01-01 open Liabilities:CreditCard USD\n  cash-flow-role: "financing"',
    )
    _, found = classes(ledger)
    assert found["Liabilities:CreditCard"].group == DEBT


def test_net_worth_by_group_at_market_value():
    [summary] = summaries()[0].values()
    assert summary.net_worth_start == 110000
    assert summary.holdings == {
        CASH: 91000,
        INVESTMENTS: 2500,  # VTI at 250
        PROPERTY: 300000,
        DEBT: -190000,
        OTHER: -1000,  # the credit card
    }
    assert summary.net_worth == 202500
    assert summary.net_worth_change == 92500
    assert (summary.investable_start, summary.investable) == (10000, 93500)


def test_income_spending_and_savings():
    [summary] = summaries()[0].values()
    assert (summary.income, summary.expenses, summary.savings) == (100000, 8000, 92000)
    assert summary.savings_rate == 92
    assert summary.top_categories == [("Expenses:Food", 6000), ("Expenses:Housing", 2000)]


def test_spending_ratios():
    [summary] = summaries()[0].values()
    # A year's spending against net worth, and investable assets, at its start.
    assert summary.spending_rate == Decimal(100 * 8000) / 110000
    assert summary.withdrawal_rate == Decimal(100 * 8000) / 10000
    assert summary.months_of_cash == Decimal(12 * 91000) / 8000


def test_debt_paydown_excludes_credit_cards():
    [summary] = summaries()[0].values()
    assert summary.debts == [
        Debt("Liabilities:Home:Mortgage", start=200000, borrowed=0, paid=10000, end=190000)
    ]


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
    assert Debt("Liabilities:CarLoan", start=0, borrowed=20000, paid=0, end=20000) in summary.debts


def test_consecutive_years_chain():
    found, _ = summaries(years=(2023, 2024))
    assert found[2023].net_worth_start == 0
    assert found[2023].net_worth == 110000 == found[2024].net_worth_start
    assert found[2023].spending_rate is None  # no net worth at its start
    assert found[2023].withdrawal_rate is None
    assert found[2023].savings_rate is None  # no income


def test_year_to_date_is_annualized():
    found, _ = summaries(today=datetime.date(2024, 7, 1))
    summary = found[2024]
    assert not summary.complete
    assert summary.end == datetime.date(2024, 7, 2)
    assert summary.days == 183
    assert summary.annual_expenses == Decimal(8000) * 365 / 183
    # VTI's only price, on 2024-12-31, is after today, so it's valued at cost.
    assert summary.holdings[INVESTMENTS] == 2000


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
