import textwrap

import pytest
from beancount import loader
from beancount.core.data import Transaction

from beancount_sg.plugins.flag_balanced import flag_balanced

HEADER = """
plugin "beancount_sg.plugins.flag_balanced"

2020-01-01 open Assets:Bank
2020-01-01 open Assets:Bank:Savings
2020-01-01 open Assets:Cash
2020-01-01 open Liabilities:Card
2020-01-01 open Expenses:Food
2020-01-01 open Income:Salary
2020-01-01 open Equity:Opening
"""


def load(ledger: str, plugin: bool = True):
    text = HEADER + textwrap.dedent(ledger)
    if not plugin:
        text = text.replace('plugin "beancount_sg.plugins.flag_balanced"', "")
    entries, errors, options_map = loader.load_string(text)
    assert errors == []
    return entries, options_map


def txns(entries) -> dict[str, Transaction]:
    return {e.narration: e for e in entries if isinstance(e, Transaction)}


def posting_flags(txn: Transaction) -> dict[str, str | None]:
    return {p.account: p.flag for p in txn.postings}


def test_transaction_before_balance_is_okay():
    t = txns(
        load("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)[0]
    )["Lunch"]
    assert t.flag == "*"
    assert posting_flags(t) == {"Assets:Cash": "*", "Expenses:Food": None}


def test_transaction_on_balance_date_is_not_covered():
    # A balance assertion checks the balance at the *start* of its date.
    t = txns(
        load("""
        2020-03-01 * "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  0 USD
        """)[0]
    )["Lunch"]
    assert t.flag == "!"
    assert posting_flags(t) == {"Assets:Cash": "!", "Expenses:Food": None}


def test_transaction_after_last_balance_is_warning():
    t = txns(
        load("""
        2020-02-01 balance Assets:Cash  0 USD

        2020-03-01 * "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food
        """)[0]
    )["Lunch"]
    assert t.flag == "!"
    assert posting_flags(t)["Assets:Cash"] == "!"


def test_latest_balance_determines_coverage():
    t = txns(
        load("""
        2020-02-01 balance Assets:Cash  0 USD

        2020-02-15 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)[0]
    )["Lunch"]
    assert t.flag == "*"
    assert posting_flags(t)["Assets:Cash"] == "*"


def test_mixed_coverage_flags_transaction_warning():
    t = txns(
        load("""
        2020-02-01 * "Pay card from bank"
          Assets:Bank       -50 USD
          Liabilities:Card   50 USD

        2020-03-01 balance Assets:Bank  -50 USD
        2020-01-15 balance Liabilities:Card  0 USD
        """)[0]
    )["Pay card from bank"]
    assert t.flag == "!"
    assert posting_flags(t) == {"Assets:Bank": "*", "Liabilities:Card": "!"}


def test_untracked_accounts_are_untouched():
    t = txns(
        load("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Bank  0 USD
        """)[0]
    )["Lunch"]
    assert t.flag == "!"
    assert posting_flags(t) == {"Assets:Cash": None, "Expenses:Food": None}


def test_untracked_account_does_not_block_okay():
    t = txns(
        load("""
        2020-02-01 ! "Withdraw"
          Assets:Bank  -20 USD
          Assets:Cash   20 USD

        2020-03-01 balance Assets:Bank  -20 USD
        """)[0]
    )["Withdraw"]
    assert t.flag == "*"
    assert posting_flags(t) == {"Assets:Bank": "*", "Assets:Cash": None}


def test_parent_balance_covers_subaccount():
    t = txns(
        load("""
        2020-02-01 * "Interest"
          Assets:Bank:Savings  1 USD
          Income:Salary

        2020-03-01 balance Assets:Bank  1 USD
        """)[0]
    )["Interest"]
    assert t.flag == "*"
    assert posting_flags(t)["Assets:Bank:Savings"] == "*"


def test_subaccount_balance_does_not_cover_parent():
    t = txns(
        load("""
        2020-02-01 ! "Deposit"
          Assets:Bank  5 USD
          Income:Salary

        2020-03-01 balance Assets:Bank:Savings  0 USD
        """)[0]
    )["Deposit"]
    assert t.flag == "!"
    assert posting_flags(t)["Assets:Bank"] is None


def test_subaccount_uses_later_of_own_and_parent_balance():
    t = txns(
        load("""
        2020-02-01 balance Assets:Bank  0 USD

        2020-02-15 ! "Interest"
          Assets:Bank:Savings  1 USD
          Income:Salary

        2020-03-01 balance Assets:Bank:Savings  1 USD
        """)[0]
    )["Interest"]
    assert t.flag == "*"


def test_balance_is_per_currency():
    t = txns(
        load("""
        2020-02-01 ! "Euro lunch"
          Assets:Cash  -10 EUR
          Expenses:Food

        2020-03-01 balance Assets:Cash  0 USD
        """)[0]
    )["Euro lunch"]
    assert t.flag == "!"
    assert posting_flags(t)["Assets:Cash"] is None


def test_covered_warning_flags_are_cleared():
    t = txns(
        load("""
        2020-02-01 ! "Lunch"
          ! Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)[0]
    )["Lunch"]
    assert t.flag == "*"
    assert posting_flags(t)["Assets:Cash"] == "*"


def test_special_transaction_flags_are_preserved():
    t = txns(
        load("""
        2020-02-01 # "Tagged lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)[0]
    )["Tagged lunch"]
    assert t.flag == "#"
    assert posting_flags(t)["Assets:Cash"] is None


def test_padding_transactions_load_cleanly():
    entries, _ = load("""
    2020-01-02 pad Assets:Bank Equity:Opening
    2020-02-01 balance Assets:Bank  100 USD

    2020-02-15 * "Spend"
      Assets:Bank  -10 USD
      Expenses:Food
    """)
    by_name = txns(entries)
    assert by_name["Spend"].flag == "!"
    padding = [t for t in by_name.values() if t.flag == "P"]
    assert len(padding) == 1


@pytest.mark.parametrize("flag", ["*", "!"])
def test_unchanged_entries_keep_identity(flag):
    entries, options_map = load(
        f"""
        2020-02-01 {flag} "Lunch"
          * Assets:Cash  -10 USD
          Expenses:Food

        2020-01-15 * "Unrelated"
          Assets:Bank  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """,
        plugin=False,
    )
    new_entries, errors = flag_balanced(entries, options_map)
    assert errors == []
    old, new = txns(entries), txns(new_entries)
    assert new["Unrelated"] is old["Unrelated"]
    assert (new["Lunch"] is old["Lunch"]) == (flag == "*")
    assert new["Lunch"].flag == "*"


def test_input_list_is_not_mutated():
    entries, options_map = load(
        """
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """,
        plugin=False,
    )
    snapshot = list(entries)
    new_entries, _ = flag_balanced(entries, options_map)
    assert entries == snapshot
    assert txns(entries)["Lunch"].flag == "!"
    assert txns(new_entries)["Lunch"].flag == "*"


def test_no_balances_returns_entries_unchanged():
    entries, options_map = load(
        """
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food
        """,
        plugin=False,
    )
    new_entries, errors = flag_balanced(entries, options_map)
    assert new_entries is entries
    assert errors == []
