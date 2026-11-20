import pytest
from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES

from beancount_sg.cash_flow_roles import (
    CASH,
    FINANCING,
    INVESTING,
    OPERATING,
    account_roles,
    default_role,
    notable_accounts,
)
from beancount_sg.testing import load

LEDGER = """
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
2020-01-01 open Income:Salary
2020-01-01 open Expenses:Food
"""


def test_roles_are_declared_inherited_or_the_default():
    entries, _ = load(LEDGER)
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    assert {account: (role.role, role.declared_by) for account, role in roles.items()} == {
        "Assets:Bank:Checking": (CASH, None),  # by name
        "Assets:Bank:CD": (INVESTING, "Assets:Bank:CD"),  # declared, over its name
        "Assets:MoneyMarket": (CASH, "Assets:MoneyMarket"),
        "Assets:Brokerage": (INVESTING, None),
        "Assets:Retirement": (INVESTING, "Assets:Retirement"),
        # Inherited from its parent, over its name.
        "Assets:Retirement:Cash": (INVESTING, "Assets:Retirement"),
        "Liabilities:CreditCard:Visa": (FINANCING, None),
        "Liabilities:Mortgage": (FINANCING, None),
        "Liabilities:CarLoan": (FINANCING, None),  # the default: its invalid role is ignored
        "Equity:Opening": (FINANCING, None),
        "Income:Salary": (OPERATING, None),
        "Expenses:Food": (OPERATING, None),
    }
    assert roles["Assets:Retirement:Cash"].declared
    assert not roles["Assets:Brokerage"].declared


def test_unknown_roles_are_errors():
    entries, _ = load(LEDGER)
    _, errors = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    [error] = errors
    assert error.message == (
        "Liabilities:CarLoan: cash-flow-role 'invsting' isn't one of"
        " cash, operating, investing, financing; it's ignored"
    )
    assert error.entry.account == "Liabilities:CarLoan"


def test_inheritance_does_not_depend_on_open_order():
    # The subaccount is opened, and listed, before its parent.
    entries, _ = load("""
2020-01-01 open Assets:Retirement:Cash
2021-01-01 open Assets:Retirement
  cash-flow-role: "investing"
""")
    roles, _ = account_roles(entries, DEFAULT_ACCOUNT_TYPES)
    assert roles["Assets:Retirement:Cash"].role == INVESTING
    assert roles["Assets:Retirement:Cash"].declared_by == "Assets:Retirement"


@pytest.mark.parametrize(
    ("account", "role"),
    [
        ("Expenses:CreditCardPayment", FINANCING),
        ("Expenses:LoanRepayment", FINANCING),
        ("Expenses:MortgageRepayment", FINANCING),
        ("Expenses:Mortgage:Payment", FINANCING),
        ("Expenses:Car:LoanPayment", FINANCING),
        ("Expenses:Rent:Payment", OPERATING),
        ("Expenses:Mortgage:Interest", OPERATING),
        ("Expenses:Insurance", OPERATING),
    ],
)
def test_debt_payment_accounts_default_to_financing(account, role):
    assert default_role(account, DEFAULT_ACCOUNT_TYPES) == role


def test_notable_accounts_skip_those_classified_as_their_parent():
    classified = {
        "Assets:Bank": CASH,
        "Assets:Bank:Checking": CASH,  # as its parent
        "Assets:Bank:CD": INVESTING,  # differs
        "Assets:Bank:CD:Ladder": INVESTING,  # as its parent, Assets:Bank:CD
        "Assets:Brokerage": INVESTING,  # two levels: always
        "Assets:Retirement:401k": INVESTING,  # no parent listed
        "Assets:Retirement:401k:Cash": CASH,  # differs
        "Liabilities:CreditCard:Visa": FINANCING,  # no parent listed
    }
    assert notable_accounts(classified) == [
        "Assets:Bank",
        "Assets:Bank:CD",
        "Assets:Brokerage",
        "Assets:Retirement:401k",
        "Assets:Retirement:401k:Cash",
        "Liabilities:CreditCard:Visa",
    ]
