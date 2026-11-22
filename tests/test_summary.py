"""Tests for the financial summary (see ext/test_summary.py for the Fava report)."""

import datetime
from decimal import Decimal

from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES

from beancount_sg.cash_flow_roles import account_roles
from beancount_sg.summary import (
    BANK,
    DEBTS,
    INVESTMENTS,
    accounts,
    bills,
    label,
    last4,
    secured_loans,
    summarize,
)
from beancount_sg.summary.cli import main
from beancount_sg.summary.pdf import render
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


OPTIONS = 'option "title" "Test"\noption "operating_currency" "USD"\n'


def test_summarize_values_holdings_at_market_value():
    ledger = (
        OPTIONS
        + LEDGER
        + """
2020-01-01 open Assets:Brokerage
2024-04-01 * "Buy"
  Assets:Brokerage  10 VTI {100 USD}
  Assets:Bank:Checking
2024-12-30 price VTI  150 USD
2024-06-01 * "Euros, without a price"
  Assets:Brokerage  20 EUR
  Equity:Opening
"""
    )
    entries, options = load(ledger)
    summary = summarize(entries, options, TODAY)
    found = {item.account: item for item in summary.open_accounts}
    assert found["Assets:Brokerage"].value == {"USD": 1500, "EUR": 20}
    assert found["Assets:Bank:Checking"].value == {"USD": 2580}
    # 2580 + 300000 + 1500 in USD; 199000 on the mortgage and 100 on the card.
    assert summary.assets == {"USD": 304080, "EUR": 20}
    assert summary.debts == {"USD": 199100}
    assert summary.net_worth == {"USD": 104980, "EUR": 20}
    assert summary.money(summary.net_worth) == "20.00 EUR, 104,980.00 USD"
    assert [loan.asset for loan in summary.secured_loans] == ["Assets:Home"]
    assert summary.title == "Test"


def test_summarize_as_of_a_date():
    entries, options = load(OPTIONS + LEDGER)
    summary = summarize(entries, options, datetime.date(2024, 2, 10))
    found = {item.account: item for item in summary.open_accounts}
    # Not the card payment on the 25th, or the old account's closing in June.
    assert found["Liabilities:CreditCard"].amount == {"USD": 120}
    assert not summary.closed_accounts


def test_render_is_a_pdf():
    entries, options = load(OPTIONS + LEDGER)
    assert render(summarize(entries, options, TODAY)).startswith(b"%PDF")


def test_the_command_writes_the_pdf(tmp_path, capsys):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(OPTIONS + LEDGER)
    output = tmp_path / "out.pdf"
    assert main([str(ledger), "--output", str(output), "--date", "2024-12-31"]) == 0
    assert output.read_bytes().startswith(b"%PDF")
    assert capsys.readouterr().out == f"Wrote {output}\n"


def test_the_command_names_the_pdf_by_date(tmp_path, monkeypatch):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(OPTIONS + LEDGER)
    monkeypatch.chdir(tmp_path)
    main([str(ledger), "--date", "2024-12-31"])
    assert (tmp_path / "financial-summary-2024-12-31.pdf").exists()
