"""Tests for the financial summary (see ext/test_summary.py for the Fava report)."""

import datetime
from decimal import Decimal

import pytest
from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES

from beancount_sg.cash_flow_roles import CASH, INVESTING, Role, account_roles
from beancount_sg.summary import (
    LINES,
    accounts,
    asset_line,
    bills,
    label,
    last4,
    liability_line,
    summarize,
)
from beancount_sg.summary.cli import main
from beancount_sg.summary.pdf import render
from beancount_sg.testing import load

LEDGER = """
2020-01-01 open Assets:Bank
  institution: "First Bank"
  owner: "Joint (Alex and Sam)"
2020-01-01 open Assets:Bank:Checking USD
  account-number: "000123454321"
2020-01-01 open Assets:Home USD
  owner: "Joint (Alex and Sam)"
2020-01-01 open Liabilities:Home:Mortgage USD
  institution: "Hometown Lending"
  owner: "Alex"
  bill: "Mortgage"
2020-01-01 open Liabilities:CreditCard USD
  institution: "Card Co"
  owner: "Sam"
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
OPTIONS = 'option "title" "Test"\noption "operating_currency" "USD"\n'


def summary_of(ledger=LEDGER, date=TODAY):
    entries, options = load(OPTIONS + ledger)
    return summarize(entries, options, date)


def test_last4_and_labels():
    assert last4("0001-2345-4321") == "4321"
    assert last4(Decimal("4111111111113456")) == "3456"
    assert last4("no digits") is None
    assert label("Assets:Bank:Checking") == "Bank › Checking"


def test_accounts_by_line_with_institutions_and_owners():
    summary = summary_of()
    # Assets:Bank, only giving its subaccounts an institution and owner, isn't listed.
    assert [
        (item.account, item.line.key, item.institution, item.owner, item.number)
        for item in summary.open_accounts
    ] == [
        ("Assets:Bank:Checking", "cash", "First Bank", "Joint (Alex and Sam)", "4321"),
        ("Assets:Home", "real-estate", None, "Joint (Alex and Sam)", None),
        ("Liabilities:CreditCard", "credit-cards", "Card Co", "Sam", "3456"),
        ("Liabilities:Home:Mortgage", "mortgages", "Hometown Lending", "Alex", None),
    ]
    [old] = summary.closed_accounts
    assert (old.account, old.institution, old.number, old.closed) == (
        "Assets:Bank:Old",
        "First Bank",
        "8802",
        datetime.date(2024, 6, 30),
    )


def test_the_statement():
    summary = summary_of()
    assert [(line.key, total) for line, _, total in summary.lines(liability=False)] == [
        ("cash", {"USD": 3580}),
        ("real-estate", {"USD": 300000}),
    ]
    # What's owed is positive.
    assert [(line.key, total) for line, _, total in summary.lines(liability=True)] == [
        ("credit-cards", {"USD": 100}),
        ("mortgages", {"USD": 199000}),
    ]
    assert (summary.assets, summary.debts, summary.net_worth) == (
        {"USD": 303580},
        {"USD": 199100},
        {"USD": 104480},
    )


INVESTMENT, CASH_ROLE = Role(INVESTING), Role(CASH)


@pytest.mark.parametrize(
    ("account", "role", "loans", "key"),
    [
        ("Assets:Bank:Checking", CASH_ROLE, [], "cash"),
        ("Assets:Bank:Savings", CASH_ROLE, [], "savings"),
        ("Assets:Bank:MoneyMarket", CASH_ROLE, [], "savings"),
        ("Assets:Vanguard:RothIRA", INVESTMENT, [], "retirement"),
        ("Assets:Fidelity:401k:Cash", CASH_ROLE, [], "retirement"),  # cash, but retirement
        ("Assets:Schwab:IRA", INVESTMENT, [], "retirement"),
        ("Assets:Receivable:Alex", INVESTMENT, [], "receivables"),
        ("Assets:LifeInsurance:Policy", INVESTMENT, [], "life-insurance"),
        ("Assets:Car", INVESTMENT, [], "automobiles"),
        ("Assets:Home", INVESTMENT, [], "real-estate"),
        ("Assets:Rental:MainSt", INVESTMENT, [], "real-estate"),
        ("Assets:MainSt", INVESTMENT, ["Liabilities:MainSt:Mortgage"], "real-estate"),
        ("Assets:Truck2", INVESTMENT, [], "automobiles"),
        ("Assets:Brokerage", INVESTMENT, [], "stocks-bonds"),
        ("Assets:Brokerage", INVESTMENT, ["Liabilities:Brokerage:Margin"], "stocks-bonds"),
    ],
)
def test_asset_lines_inferred(account, role, loans, key):
    assert asset_line(account, role, {}, loans)[0].key == key


@pytest.mark.parametrize(
    ("account", "secures", "key"),
    [
        ("Liabilities:Home:Mortgage", None, "mortgages"),
        ("Liabilities:HELOC", None, "mortgages"),
        ("Liabilities:CreditCard:Visa", None, "credit-cards"),
        ("Liabilities:Amex", None, "credit-cards"),
        ("Liabilities:PropertyTax", None, "unpaid-taxes"),
        ("Liabilities:CarLoan", None, "auto-loans"),
        ("Liabilities:StudentLoan", None, "installment-loans"),
        ("Liabilities:MainSt:Lender", LINES["real-estate"], "mortgages"),
        ("Liabilities:Boat2:Lender", LINES["automobiles"], "auto-loans"),
        ("Liabilities:BankLoan", None, "notes-payable"),
        ("Liabilities:Owed:Friend", None, "other-liabilities"),
    ],
)
def test_liability_lines_inferred(account, secures, key):
    assert liability_line(account, {}, secures)[0].key == key


def test_declared_types_on_an_account_a_parent_or_a_commodity():
    ledger = (
        LEDGER
        + """
2020-01-01 open Assets:Valuables
  asset-type: "personal-property"
2020-01-01 open Assets:Valuables:Art USD
2020-01-01 commodity MAINST
  asset-type: "real-estate"
2020-01-01 open Assets:Holdings MAINST
2020-01-01 open Liabilities:Family USD
  liability-type: "notes-payable"
2020-01-01 open Assets:Bank:Wrong USD
  asset-type: "mortgages"
2024-01-02 * "Opening"
  Assets:Valuables:Art  5000 USD
  Assets:Holdings  1 MAINST {200000 USD}
  Liabilities:Family  -1000 USD
  Assets:Bank:Wrong  1 USD
  Equity:Opening
"""
    )
    found = {item.account: item for item in summary_of(ledger).open_accounts}
    assert (found["Assets:Valuables:Art"].line.key, found["Assets:Valuables:Art"].reason) == (
        "personal-property",
        "asset-type: personal-property on Assets:Valuables",
    )
    assert (found["Assets:Holdings"].line.key, found["Assets:Holdings"].reason) == (
        "real-estate",
        "asset-type: real-estate on commodity MAINST",
    )
    assert found["Liabilities:Family"].line.key == "notes-payable"
    # A liability type on an asset is ignored.
    assert found["Assets:Bank:Wrong"].line.key == "cash"


def test_real_estate_and_vehicles():
    [home] = summary_of().properties
    assert home.asset.account == "Assets:Home"
    [mortgage] = home.loans
    assert (mortgage.account.account, mortgage.account.institution) == (
        "Liabilities:Home:Mortgage",
        "Hometown Lending",
    )
    assert mortgage.payments.last_amount == {"USD": 1000}
    assert (home.value, home.owed, home.equity) == (
        {"USD": 300000},
        {"USD": 199000},
        {"USD": 101000},
    )


def test_a_property_without_a_loan():
    ledger = (
        LEDGER
        + "2020-01-01 open Assets:Car USD\n"
        + '2024-01-02 * "Car"\n  Assets:Car  9000 USD\n  Equity:Opening\n'
    )
    [car] = [item for item in summary_of(ledger).properties if item.asset.account == "Assets:Car"]
    assert (car.loans, car.equity) == ([], {"USD": 9000})


def test_bills():
    entries, _ = load(LEDGER)
    found = {bill.name: bill.payments for bill in bills(entries, DEFAULT_ACCOUNT_TYPES, TODAY)}
    assert sorted(found) == ["CreditCard", "Electric", "Mortgage"]  # TRUE: the account's label
    electric = found["Electric"]
    assert (electric.last_paid, electric.last_amount, electric.paid_from) == (
        datetime.date(2024, 3, 8),
        {"USD": 100},
        ["Liabilities:CreditCard"],
    )
    assert (electric.count, electric.yearly) == (2, {"USD": 220})
    # Paying the card: the payment adds to it; charges don't.
    card = found["CreditCard"]
    assert (card.count, card.last_amount, card.paid_from) == (
        1,
        {"USD": 420},
        ["Assets:Bank:Checking"],
    )


def test_bills_count_only_the_last_12_months():
    entries, _ = load(LEDGER)
    later = datetime.date(2025, 2, 15)
    found = {bill.name: bill.payments for bill in bills(entries, DEFAULT_ACCOUNT_TYPES, later)}
    # The February 8th payment is more than a year before.
    assert (found["Electric"].count, found["Electric"].yearly) == (1, {"USD": 100})


def test_values_at_market_value():
    ledger = (
        LEDGER
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
    summary = summary_of(ledger)
    found = {item.account: item for item in summary.open_accounts}
    assert found["Assets:Brokerage"].value == {"USD": 1500, "EUR": 20}
    assert summary.net_worth == {"USD": 104980, "EUR": 20}
    assert summary.money(summary.net_worth) == "20.00 EUR, 104,980.00 USD"


def test_summarize_as_of_a_date():
    summary = summary_of(date=datetime.date(2024, 2, 10))
    found = {item.account: item for item in summary.open_accounts}
    # Not the card payment on the 25th, or the old account's closing in June.
    assert found["Liabilities:CreditCard"].amount == {"USD": 120}
    assert not summary.closed_accounts


def test_accounts_are_by_institution_within_a_line():
    ledger = LEDGER + (
        '2020-01-01 open Assets:Bank:Zebra USD\n  institution: "A Credit Union"\n'
        '2024-01-05 * "Deposit"\n  Assets:Bank:Zebra  10 USD\n  Equity:Opening\n'
    )
    cash = [item.account for item in summary_of(ledger).open_accounts if item.line.key == "cash"]
    assert cash == ["Assets:Bank:Zebra", "Assets:Bank:Checking"]  # A Credit Union, First Bank


def test_a_parent_with_its_own_balance_is_listed():
    entries, _ = load(LEDGER)
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    values = {"Assets:Bank": {"USD": Decimal(5)}}
    open_accounts, _ = accounts(entries, roles, DEFAULT_ACCOUNT_TYPES, values)
    assert "Assets:Bank" in [item.account for item in open_accounts]


def test_missing_details():
    assert [item.account for item in summary_of().missing_details] == ["Assets:Home"]


def test_render_is_a_pdf():
    assert render(summary_of()).startswith(b"%PDF")


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
