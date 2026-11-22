"""Tests for the Financial Summary's contents (see test_summary.py for the page and PDF)."""

import datetime
from decimal import Decimal

from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES

from beancount_sg.cash_flow_roles import account_roles
from beancount_sg.ext.summary.contents import (
    BANK,
    DEBTS,
    INVESTMENTS,
    accounts,
    bills,
    label,
    last4,
    secured_loans,
)
from beancount_sg.testing import load

LEDGER = """
2020-01-01 open Assets:Bank:Checking USD
  account-number: "000123454321"
2020-01-01 open Assets:Home USD
2020-01-01 open Liabilities:Home:Mortgage USD
  bill: "Mortgage"
2020-01-01 open Liabilities:CreditCard USD
  account-number: 4111111111113456
  bill: TRUE
2020-01-01 open Assets:Bank:Old USD
  account-number: "88-02"
2020-01-01 open Equity:Opening
2020-01-01 open Expenses:Electric USD
  bill: "Electric"
2020-01-01 open Expenses:Food USD

2023-12-31 * "Opening balances"
  Assets:Bank:Checking  5000 USD
  Assets:Home  300000 USD
  Liabilities:Home:Mortgage  -200000 USD
  Equity:Opening

2024-02-01 * "Mortgage payment"
  Liabilities:Home:Mortgage  1000 USD
  Assets:Bank:Checking

2024-02-08 * "Electric, on the card"
  Expenses:Electric  120 USD
  Liabilities:CreditCard

2024-02-20 * "Groceries, on the card"
  Expenses:Food  300 USD
  Liabilities:CreditCard

2024-02-25 * "Card payment"
  Liabilities:CreditCard  420 USD
  Assets:Bank:Checking

2024-03-08 * "Electric, on the card"
  Expenses:Electric  100 USD
  Liabilities:CreditCard

2024-06-30 close Assets:Bank:Old
"""
TODAY = datetime.date(2024, 12, 31)


def test_last4_and_labels():
    assert last4("0001-2345-4321") == "4321"
    assert last4(Decimal("4111111111113456")) == "3456"
    assert last4("no digits") is None
    assert label("Assets:Bank:Checking") == "Bank › Checking"


def found_accounts():
    entries, _ = load(LEDGER)
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    values = {"Assets:Bank:Checking": {"USD": Decimal(3580)}}
    return accounts(entries, roles, DEFAULT_ACCOUNT_TYPES, values)


def test_open_and_closed_accounts_by_group():
    open_accounts, closed = found_accounts()
    assert [(item.account, item.group, item.number) for item in open_accounts] == [
        ("Assets:Bank:Checking", BANK, "4321"),
        ("Assets:Home", INVESTMENTS, None),
        ("Liabilities:CreditCard", DEBTS, "3456"),
        ("Liabilities:Home:Mortgage", DEBTS, None),
    ]
    assert open_accounts[0].amount == {"USD": 3580}
    [old] = closed
    assert (old.account, old.number, old.closed) == (
        "Assets:Bank:Old",
        "8802",
        datetime.date(2024, 6, 30),
    )


def test_a_loan_amount_is_whats_owed():
    entries, _ = load(LEDGER)
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    [mortgage] = [
        item
        for item in accounts(
            entries,
            roles,
            DEFAULT_ACCOUNT_TYPES,
            {"Liabilities:Home:Mortgage": {"USD": Decimal(-199000)}},
        )[0]
        if item.account == "Liabilities:Home:Mortgage"
    ]
    assert mortgage.amount == {"USD": 199000}


def test_secured_loans_match_the_assets_path():
    open_accounts, _ = found_accounts()
    totals = {
        "Assets:Home": {"USD": Decimal(300000)},
        "Liabilities:Home": {"USD": Decimal(-199000)},
    }
    [home] = secured_loans(open_accounts, totals, DEFAULT_ACCOUNT_TYPES)
    assert (home.asset, home.loans) == ("Assets:Home", ["Liabilities:Home:Mortgage"])
    assert (home.value, home.owed, home.equity) == (
        {"USD": 300000},
        {"USD": 199000},
        {"USD": 101000},
    )


def test_bills():
    entries, _ = load(LEDGER)
    found = {bill.name: bill for bill in bills(entries, DEFAULT_ACCOUNT_TYPES, TODAY)}
    assert sorted(found) == ["CreditCard", "Electric", "Mortgage"]  # TRUE: the account's label
    electric = found["Electric"]
    assert (electric.last_paid, electric.last_amount, electric.paid_from) == (
        datetime.date(2024, 3, 8),
        {"USD": 100},
        ["Liabilities:CreditCard"],
    )
    assert (electric.payments, electric.yearly) == (2, {"USD": 220})
    # Paying the card: the payment adds to it; charges don't.
    card = found["CreditCard"]
    assert (card.payments, card.last_amount, card.paid_from) == (
        1,
        {"USD": 420},
        ["Assets:Bank:Checking"],
    )
    assert found["Mortgage"].last_amount == {"USD": 1000}


def test_bills_count_only_the_last_12_months():
    entries, _ = load(LEDGER)
    later = datetime.date(2025, 2, 15)
    found = {bill.name: bill for bill in bills(entries, DEFAULT_ACCOUNT_TYPES, later)}
    # The February 8th payment is more than a year before.
    assert (found["Electric"].payments, found["Electric"].yearly) == (1, {"USD": 100})
    assert found["Electric"].last_paid == datetime.date(2024, 3, 8)
