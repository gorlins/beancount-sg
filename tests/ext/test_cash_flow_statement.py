"""Tests for the Cash Flow report's calculations (see test_cash_flow.py for the page)."""

import datetime
from decimal import Decimal

from beancount.core import prices
from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES

from beancount_sg.cash_flow_roles import FINANCING, INVESTING, OPERATING, account_roles
from beancount_sg.ext.cash_flow.statement import by_interval, statement
from beancount_sg.testing import load

LEDGER = """
2020-01-01 open Assets:Bank:Checking USD
2020-01-01 open Assets:Brokerage
2020-01-01 open Liabilities:CreditCard USD
2020-01-01 open Liabilities:Mortgage USD
2020-01-01 open Equity:Opening
2020-01-01 open Income:Salary USD
2020-01-01 open Expenses:Food:Groceries USD
2020-01-01 open Expenses:Food:Dining USD
2020-01-01 open Expenses:Housing:Interest USD

2023-12-31 * "Opening balances"
  Assets:Bank:Checking  10000 USD
  Liabilities:Mortgage  -50000 USD
  Equity:Opening

2024-01-31 * "Salary"
  Assets:Bank:Checking  5000 USD
  Income:Salary

2024-02-01 * "Groceries"
  Expenses:Food:Groceries  300 USD
  Assets:Bank:Checking

2024-02-02 * "Dinner on the card"
  Expenses:Food:Dining  100 USD
  Liabilities:CreditCard

2024-02-25 * "Card payment"
  Liabilities:CreditCard  100 USD
  Assets:Bank:Checking

2024-03-01 * "Buy VTI"
  Assets:Brokerage  10 VTI {100 USD}
  Assets:Bank:Checking

2024-08-01 * "Mortgage payment"
  Liabilities:Mortgage  500 USD
  Expenses:Housing:Interest  200 USD
  Assets:Bank:Checking
"""

BEGIN, END = datetime.date(2024, 1, 1), datetime.date(2025, 1, 1)


def run(ledger=LEDGER, begin=BEGIN, end=END):
    entries, _ = load(ledger)
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    price_map = prices.build_price_map(entries)
    return statement(entries, price_map, roles, DEFAULT_ACCOUNT_TYPES, "USD", begin, end)


def test_lines_by_activity():
    result = run()
    # Income and expenses roll up to their top-level category.
    assert result.lines(OPERATING) == [
        ("Income:Salary", 5000),
        ("Expenses:Food", -400),  # groceries and dinner
        ("Expenses:Housing", -200),  # interest
    ]
    assert result.lines(INVESTING) == [("Assets:Brokerage", -1000)]
    # The card's charge and payment cancel out; the opening balances are before the period.
    assert result.lines(FINANCING) == [("Liabilities:Mortgage", -500)]
    assert {activity: result.total(activity) for activity in (OPERATING, INVESTING, FINANCING)} == {
        OPERATING: 4400,
        INVESTING: -1000,
        FINANCING: -500,
    }


def test_reconciles_with_cash():
    result = run()
    assert result.cash_start == {"Assets:Bank:Checking": 10000}
    assert result.cash_end == {"Assets:Bank:Checking": 12900}
    assert result.net_change == 2900 == result.cash_end_total - result.cash_start_total
    assert result.valuation_change == 0
    assert result.cash_accounts == ["Assets:Bank:Checking"]


def test_a_declared_role_moves_the_line():
    ledger = LEDGER.replace(
        "2020-01-01 open Assets:Brokerage",
        '2020-01-01 open Assets:Brokerage\n  cash-flow-role: "cash"',
    )
    result = run(ledger)
    # Buying VTI is now a transfer between cash accounts.
    assert result.lines(INVESTING) == []
    assert result.net_change == 3900
    assert result.cash_end["Assets:Brokerage"] == 1000  # at cost, without a price


def test_exchange_rates_change_cash_value():
    ledger = (
        LEDGER
        + """
2020-01-01 open Assets:Bank:Euro EUR
2023-12-30 * "Euros"
  Assets:Bank:Euro  100 EUR
  Equity:Opening
2023-12-30 price EUR  1.10 USD
2024-12-31 price EUR  1.20 USD
"""
    )
    result = run(ledger)
    assert result.cash_start["Assets:Bank:Euro"] == 110
    assert result.cash_end["Assets:Bank:Euro"] == 120
    assert result.valuation_change == 10  # not from any activity


def test_emergency_fund():
    ledger = (
        LEDGER
        + """
2020-01-01 open Assets:Bank:Savings USD
2023-12-31 * "Savings"
  Assets:Bank:Savings  6000 USD
  Equity:Opening
"""
    )
    result = run(ledger)
    # The 12 months up to the end are 2024: 600 spent, 50 a month.
    assert result.trailing_start == BEGIN
    assert (result.trailing_expenses, result.monthly_expenses) == (600, 50)
    assert result.savings_accounts == ["Assets:Bank:Savings"]
    assert result.months_of_cash() == Decimal(12900 + 6000) / 50
    assert result.months_of_cash(savings=False) == Decimal(12900) / 50


def test_emergency_fund_uses_12_months_whatever_the_period():
    # September alone has no spending, but the 12 months up to its end do: groceries, dining
    # and interest from February and August.
    result = run(begin=datetime.date(2024, 9, 1), end=datetime.date(2024, 10, 1))
    assert result.trailing_start == datetime.date(2023, 10, 1)
    assert result.trailing_expenses == 600
    assert result.lines(OPERATING) == []


def test_the_12_months_before_february_29th():
    result = run(begin=datetime.date(2028, 2, 1), end=datetime.date(2028, 2, 29))
    assert result.trailing_start == datetime.date(2027, 2, 28)


def test_by_interval():
    entries, _ = load(LEDGER)
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    halves = [
        (datetime.date(2024, 1, 1), datetime.date(2024, 7, 1)),
        (datetime.date(2024, 7, 1), datetime.date(2025, 1, 1)),
    ]
    found = by_interval(
        entries, prices.build_price_map(entries), roles, DEFAULT_ACCOUNT_TYPES, "USD", halves
    )
    assert [interval.date for interval in found] == [
        datetime.date(2024, 6, 30),
        datetime.date(2024, 12, 31),
    ]
    assert found[0].totals == {OPERATING: 4600, INVESTING: -1000, FINANCING: 0}
    assert found[1].totals == {OPERATING: -200, INVESTING: 0, FINANCING: -500}
