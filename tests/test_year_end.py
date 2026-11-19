"""Tests for yearly financial metrics, without Fava (see tests/ext for the report)."""

import datetime
from decimal import Decimal

import pytest
from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES

from beancount_sg.testing import load
from beancount_sg.year_end import (
    CASH,
    DEBT,
    FINANCING,
    INVESTING,
    OPERATING,
    OTHER,
    Debt,
    account_roles,
    year_end,
    years_ending,
)

LEDGER = """
option "operating_currency" "USD"

2020-01-01 open Assets:Bank:Checking USD
2020-01-01 open Assets:Brokerage
2020-01-01 open Assets:Home USD
2020-01-01 open Liabilities:CreditCard USD
2020-01-01 open Liabilities:Mortgage USD
2020-01-01 open Equity:Opening
2020-01-01 open Income:Salary USD
2020-01-01 open Expenses:Food:Groceries USD
2020-01-01 open Expenses:Housing:Interest USD

2023-01-01 * "Opening balances"
  Assets:Bank:Checking  10000 USD
  Assets:Home  300000 USD
  Liabilities:Mortgage  -200000 USD
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
  Liabilities:Mortgage  10000 USD
  Expenses:Housing:Interest  2000 USD
  Assets:Bank:Checking

2024-04-01 * "Buy VTI"
  Assets:Brokerage  10 VTI {200 USD}
  Assets:Bank:Checking

2024-12-31 price VTI  250 USD
"""


def summaries(ledger=LEDGER, years=(2024,), today=datetime.date(2030, 1, 1)):
    entries, _ = load(ledger)
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    result = year_end(entries, roles, DEFAULT_ACCOUNT_TYPES, "USD", list(years), today)
    return {summary.year: summary for summary in result.years}, result


def test_net_worth_by_group_at_market_value():
    [summary] = summaries()[0].values()
    assert summary.net_worth_start == 110000
    assert summary.holdings == {
        CASH: 91000,
        INVESTING: 302500,  # the home, and VTI at 250
        DEBT: -190000,
        OTHER: -1000,  # the credit card
    }
    assert summary.net_worth == 202500
    assert summary.net_worth_change == 92500


def test_income_spending_and_savings():
    [summary] = summaries()[0].values()
    assert (summary.income, summary.expenses, summary.savings) == (100000, 8000, 92000)
    assert summary.savings_rate == 92
    assert summary.top_categories == [("Expenses:Food", 6000), ("Expenses:Housing", 2000)]


def test_spending_ratios():
    [summary] = summaries()[0].values()
    # A year's spending against net worth at the start of the year.
    assert summary.spending_rate == Decimal(100 * 8000) / 110000
    assert summary.years_of_spending == Decimal(202500) / 8000
    assert summary.months_of_cash == Decimal(12 * 91000) / 8000


def test_debt_paydown_excludes_credit_cards():
    [summary] = summaries()[0].values()
    assert summary.debts == [
        Debt("Liabilities:Mortgage", start=200000, borrowed=0, paid=10000, end=190000)
    ]


def test_new_borrowing():
    ledger = (
        LEDGER
        + """
2024-06-01 * "Car loan"
  Assets:Bank:Checking  20000 USD
  Liabilities:CarLoan
2020-01-01 open Liabilities:CarLoan USD
"""
    )
    [summary] = summaries(ledger)[0].values()
    assert Debt("Liabilities:CarLoan", start=0, borrowed=20000, paid=0, end=20000) in summary.debts


def test_consecutive_years_chain():
    found, _ = summaries(years=(2023, 2024))
    assert found[2023].net_worth_start == 0
    assert found[2023].net_worth == 110000 == found[2024].net_worth_start
    assert found[2023].income == 0
    assert found[2023].spending_rate is None  # no net worth at its start
    assert found[2023].savings_rate is None  # no income


def test_year_to_date_is_annualized():
    found, _ = summaries(today=datetime.date(2024, 7, 1))
    summary = found[2024]
    assert not summary.complete
    assert summary.end == datetime.date(2024, 7, 2)
    assert summary.days == 183
    assert summary.expenses == 8000
    assert summary.annual_expenses == Decimal(8000) * 365 / 183
    # VTI's only price, on 2024-12-31, is after today, so it's valued at cost.
    assert summary.holdings[INVESTING] == 302000


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
    assert found[2024].holdings[INVESTING] == 302500


@pytest.mark.parametrize(
    ("end_year", "first_year", "expected"),
    [
        (2025, 2018, [2021, 2022, 2023, 2024, 2025]),  # at most 5
        (2025, 2024, [2024, 2025]),  # none before the ledger starts
        (2025, 2025, [2025]),
    ],
)
def test_years_ending(end_year, first_year, expected):
    assert years_ending(end_year, first_year) == expected


ROLES = """
2020-01-01 open Assets:Bank:Checking
2020-01-01 open Assets:Bank:CD
  cash-flow-role: "investing"
2020-01-01 open Assets:MoneyMarket
  cash-flow-role: "cash"
2020-01-01 open Assets:Brokerage
2020-01-01 open Assets:Retirement
  cash-flow-role: "investing"
2020-01-01 open Assets:Retirement:Cash
2020-01-01 open Liabilities:CreditCard:Visa
2020-01-01 open Liabilities:Mortgage
2020-01-01 open Liabilities:CarLoan
  cash-flow-role: "invsting"
2020-01-01 open Equity:Opening
2020-01-01 open Expenses:Food
"""


def test_account_roles():
    entries, _ = load(ROLES)
    roles, errors = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    assert {account: (role.role, role.declared_by) for account, role in roles.items()} == {
        "Assets:Bank:Checking": (CASH, None),  # by name
        "Assets:Bank:CD": (INVESTING, "Assets:Bank:CD"),  # declared, over its name
        "Assets:MoneyMarket": (CASH, "Assets:MoneyMarket"),
        "Assets:Brokerage": (INVESTING, None),
        "Assets:Retirement": (INVESTING, "Assets:Retirement"),
        # Inherited, over its name.
        "Assets:Retirement:Cash": (INVESTING, "Assets:Retirement"),
        "Liabilities:CreditCard:Visa": (OPERATING, None),  # a card
        "Liabilities:Mortgage": (FINANCING, None),
        "Liabilities:CarLoan": (FINANCING, None),  # the default, for an unknown role
        "Equity:Opening": (FINANCING, None),
        "Expenses:Food": (OPERATING, None),
    }
    [error] = errors
    assert (
        error.message == "Liabilities:CarLoan: unknown cash-flow-role 'invsting', using the default"
    )
