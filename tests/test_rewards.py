"""Tests for credit card rewards, without Fava (see tests/ext for the report)."""

from decimal import Decimal

import pytest

from beancount_sg.builders import A
from beancount_sg.rewards import (
    CASHBACK,
    POINTS,
    Program,
    category_rewards,
    programs,
)
from beancount_sg.testing import load

CARDS = """
2020-01-01 open Liabilities:CreditCard:Cash
  rewards: "cashback"
  rewards-rate: 1.5
  rewards-rate-groceries: 3
2020-01-01 open Liabilities:CreditCard:Sapphire
  rewards: "points"
  rewards-rate-dining: 3
  rewards-rate-food-and-drink: 2
  rewards-unit: "UR"
  rewards-point-value: 0.0125
2020-01-01 open Liabilities:CreditCard:Plain
"""


def load_programs(ledger: str = CARDS):
    entries, _ = load(ledger)
    return entries, *programs(entries)


def test_programs_from_open_metadata():
    _, found, errors = load_programs()
    assert errors == []
    assert set(found) == {"Liabilities:CreditCard:Cash", "Liabilities:CreditCard:Sapphire"}
    cash = found["Liabilities:CreditCard:Cash"]
    assert (cash.kind, cash.default_rate, cash.rates) == (
        CASHBACK,
        Decimal("1.5"),
        {"groceries": Decimal(3)},
    )
    sapphire = found["Liabilities:CreditCard:Sapphire"]
    assert (sapphire.kind, sapphire.default_rate, sapphire.unit, sapphire.point_value) == (
        POINTS,
        Decimal(1),  # the default default rate
        "UR",
        Decimal("0.0125"),
    )


@pytest.mark.parametrize(
    ("meta", "message"),
    [
        ('  rewards: "miles"', 'rewards must be "cashback" or "points"'),
        ('  rewards: "points"\n  rewards-rate: "lots"', "rewards-rate must be a number"),
    ],
)
def test_invalid_program_is_an_error(meta, message):
    _, found, [error] = load_programs(f"2020-01-01 open Liabilities:CreditCard:Bad\n{meta}\n")
    assert found == {}
    assert message in error.message
    assert error.message.startswith("Liabilities:CreditCard:Bad")


@pytest.mark.parametrize(
    ("category", "rate"),
    [("Dining", 3), ("dining", 3), ("Food and Drink", 2), ("Travel", 1), ("uncategorized", 1)],
)
def test_rate_uses_the_slugified_category_or_the_default(category, rate):
    _, found, _ = load_programs()
    assert found["Liabilities:CreditCard:Sapphire"].rate(category) == rate


def test_cashback_reward_is_a_percentage_in_the_spend_currency():
    program = Program("Liabilities:Card", CASHBACK, rates={"groceries": Decimal(3)})
    assert program.reward(A("200.00", "USD"), "Groceries") == A("6.0000", "USD")
    assert program.value(A("6", "USD"), "USD") == A("6", "USD")


def test_points_reward_is_in_its_unit_with_an_optional_value():
    program = Program("Liabilities:Card", POINTS, default_rate=Decimal(2), unit="UR")
    assert program.reward(A("100.00", "USD"), "Travel") == A("200.00", "UR")
    assert program.value(A("200", "UR"), "USD") is None
    valued = Program("Liabilities:Card", POINTS, unit="UR", point_value=Decimal("0.01"))
    assert valued.value(A("200", "UR"), "USD") == A("2.00", "USD")


def rows(ledger: str, excluded=()):
    entries, found, _ = load_programs(CARDS + ledger)
    return [
        (row.program.account.rsplit(":", 1)[-1], row.category, row.spend.to_string())
        for row in category_rewards(entries, found, excluded=excluded)
    ]


def test_points_unit_and_category_key_defaults():
    _, found, _ = load_programs("""
2020-01-01 open Liabilities:CreditCard:Card
  rewards: "points"
""")
    card = found["Liabilities:CreditCard:Card"]
    assert (card.unit, card.category_key) == ("POINTS", "category")
    assert card.reward(A("10", "USD"), "Dining") == A("10", "POINTS")


def test_category_key_reads_another_metadata_key():
    entries, found, _ = load_programs("""
2020-01-01 open Liabilities:CreditCard:Card
  rewards: "cashback"
  rewards-category-key: "bank_category"
2020-01-01 open Expenses:Food

2024-01-05 * "Bistro"
  category: "Groceries"
  bank_category: "Dining"
  Liabilities:CreditCard:Card  -40.00 USD
  Expenses:Food  30.00 USD
  Expenses:Food  10.00 USD
    bank_category: "Bakery"
""")
    assert [(row.category, row.spend) for row in category_rewards(entries, found)] == [
        ("Bakery", A("10.00", "USD")),
        ("Dining", A("30.00", "USD")),
    ]


def test_spend_is_grouped_by_card_and_category():
    assert rows("""
2024-01-05 * "Grocer"
  category: "Groceries"
  Liabilities:CreditCard:Cash  -50.00 USD
  Expenses:Food

2024-01-06 * "Grocer"
  category: "Groceries"
  Liabilities:CreditCard:Cash  -30.00 USD
  Expenses:Food

2024-01-07 * "Restaurant"
  category: "Dining"
  Liabilities:CreditCard:Sapphire  -40.00 USD
  Expenses:Food
""") == [
        ("Cash", "Groceries", "80.00 USD"),
        ("Sapphire", "Dining", "40.00 USD"),
    ]


def test_posting_category_overrides_the_transactions():
    assert rows("""
2024-01-05 * "Big box store"
  category: "Groceries"
  Liabilities:CreditCard:Cash  -100.00 USD
  Expenses:Food  60.00 USD
  Expenses:Home  40.00 USD
    category: "Home"
""") == [("Cash", "Groceries", "60.00 USD"), ("Cash", "Home", "40.00 USD")]


def test_uncategorized_spend_and_refunds():
    assert rows("""
2024-01-05 * "Shop"
  Liabilities:CreditCard:Cash  -100.00 USD
  Expenses:Shopping

2024-01-09 * "Shop" "Refund"
  Liabilities:CreditCard:Cash  25.00 USD
  Expenses:Shopping
""") == [("Cash", "uncategorized", "75.00 USD")]


def test_excluded_expense_accounts_are_not_spending():
    ledger = """
2020-01-01 open Expenses:LoanPayments:CreditCardPayment
2020-01-01 open Expenses:LoanPayments:CreditCardPayment:Cash
2020-01-01 open Expenses:LoanPaymentsOther

2024-01-05 * "Shop"
  category: "Shopping"
  Liabilities:CreditCard:Cash  -100.00 USD
  Expenses:Shopping

2024-01-07 * "Shop" "Refund"
  category: "Shopping"
  Liabilities:CreditCard:Cash  25.00 USD
  Expenses:Shopping

2024-01-09 * "Card" "AUTOPAY PYMT"
  category: "Payment/Credit"
  Liabilities:CreditCard:Cash  123.45 USD
  Expenses:LoanPayments:CreditCardPayment:Cash

2024-01-10 * "Card" "Payment"
  Liabilities:CreditCard:Cash  50.00 USD
  Expenses:LoanPayments:CreditCardPayment

2024-01-11 * "Other"
  Liabilities:CreditCard:Cash  -10.00 USD
  Expenses:LoanPaymentsOther
"""
    assert rows(ledger, excluded=["Expenses:LoanPayments:CreditCardPayment"]) == [
        ("Cash", "Shopping", "75.00 USD"),
        ("Cash", "uncategorized", "10.00 USD"),
    ]
    # Without the exclusion, the payments count as refunds.
    assert rows(ledger) == [
        ("Cash", "Payment/Credit", "-123.45 USD"),
        ("Cash", "Shopping", "75.00 USD"),
        ("Cash", "uncategorized", "-40.00 USD"),
    ]


def test_only_expenses_on_rewards_cards_count():
    assert (
        rows("""
2024-01-05 * "Card payment"
  Liabilities:CreditCard:Cash  500.00 USD
  Assets:Checking

2024-01-06 * "Statement credit"
  Liabilities:CreditCard:Cash  10.00 USD
  Income:Rewards

2024-01-07 * "No rewards on this card"
  Liabilities:CreditCard:Plain  -20.00 USD
  Expenses:Food

2024-01-08 * "Paid with cash"
  Assets:Cash  -20.00 USD
  Expenses:Food
""")
        == []
    )


def test_card_subaccounts_count_and_two_cards_are_skipped():
    assert rows("""
2024-01-05 * "Authorized user"
  Liabilities:CreditCard:Cash:Spouse  -20.00 USD
  Expenses:Food

2024-01-06 * "Split between two cards"
  Liabilities:CreditCard:Cash  -10.00 USD
  Liabilities:CreditCard:Sapphire  -10.00 USD
  Expenses:Food
""") == [("Cash", "uncategorized", "20.00 USD")]
