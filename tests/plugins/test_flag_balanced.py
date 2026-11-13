import textwrap

import pytest
from beancount import loader
from beancount.core.data import filter_txns
from beancount.core.flags import FLAG_OKAY, FLAG_PADDING, FLAG_TRANSFER, FLAG_WARNING

from beancount_sg.plugins.flag_balanced import flag_balanced

PLUGIN = 'plugin "beancount_sg.plugins.flag_balanced"\n'

ACCOUNTS = """
2020-01-01 open Assets:Bank
2020-01-01 open Assets:Bank:Savings
2020-01-01 open Assets:Cash
2020-01-01 open Liabilities:Card
2020-01-01 open Expenses:Food
2020-01-01 open Income:Salary
2020-01-01 open Equity:Opening
"""


def load(ledger: str, plugin: bool = True):
    """Load a ledger with the standard accounts open; fail on any load error."""
    text = (PLUGIN if plugin else "") + ACCOUNTS + textwrap.dedent(ledger)
    entries, errors, options_map = loader.load_string(text)
    assert errors == []
    return entries, options_map


def load_txns(ledger: str):
    """Load a ledger with the plugin enabled and return its transactions in date order."""
    entries, _ = load(ledger)
    return list(filter_txns(entries))


def test_transaction_before_balance_is_okay():
    [txn] = load_txns("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)
    assert txn.flag == FLAG_OKAY
    assert [p.flag for p in txn.postings] == [FLAG_OKAY, None]


def test_transaction_on_balance_date_is_not_covered():
    # A balance assertion checks the balance at the *start* of its date.
    [txn] = load_txns("""
        2020-03-01 * "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  0 USD
        """)
    assert txn.flag == FLAG_WARNING
    assert [p.flag for p in txn.postings] == [FLAG_WARNING, None]


def test_transaction_after_last_balance_is_warning():
    [txn] = load_txns("""
        2020-02-01 balance Assets:Cash  0 USD

        2020-03-01 * "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food
        """)
    assert txn.flag == FLAG_WARNING
    assert [p.flag for p in txn.postings] == [FLAG_WARNING, None]


def test_latest_balance_determines_coverage():
    [txn] = load_txns("""
        2020-02-01 balance Assets:Cash  0 USD

        2020-02-15 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)
    assert txn.flag == FLAG_OKAY
    assert [p.flag for p in txn.postings] == [FLAG_OKAY, None]


def test_mixed_coverage_flags_transaction_warning():
    [txn] = load_txns("""
        2020-01-15 balance Liabilities:Card  0 USD

        2020-02-01 * "Pay card from bank"
          Assets:Bank       -50 USD
          Liabilities:Card   50 USD

        2020-03-01 balance Assets:Bank  -50 USD
        """)
    assert txn.flag == FLAG_WARNING
    assert [p.flag for p in txn.postings] == [FLAG_OKAY, FLAG_WARNING]


def test_multiple_postings_to_same_account():
    [txn] = load_txns("""
        2020-02-01 ! "Split lunch"
          Assets:Cash  -6 USD
          Assets:Cash  -4 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)
    assert txn.flag == FLAG_OKAY
    assert [p.flag for p in txn.postings] == [FLAG_OKAY, FLAG_OKAY, None]


def test_untracked_accounts_are_untouched():
    [txn] = load_txns("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Bank  0 USD
        """)
    assert txn.flag == FLAG_WARNING
    assert [p.flag for p in txn.postings] == [None, None]


def test_untracked_account_does_not_block_okay():
    [txn] = load_txns("""
        2020-02-01 ! "Withdraw"
          Assets:Bank  -20 USD
          Assets:Cash   20 USD

        2020-03-01 balance Assets:Bank  -20 USD
        """)
    assert txn.flag == FLAG_OKAY
    assert [p.flag for p in txn.postings] == [FLAG_OKAY, None]


def test_parent_balance_covers_subaccount():
    [txn] = load_txns("""
        2020-02-01 * "Interest"
          Assets:Bank:Savings  1 USD
          Income:Salary

        2020-03-01 balance Assets:Bank  1 USD
        """)
    assert txn.flag == FLAG_OKAY
    assert [p.flag for p in txn.postings] == [FLAG_OKAY, None]


def test_subaccount_balance_does_not_cover_parent():
    [txn] = load_txns("""
        2020-02-01 ! "Deposit"
          Assets:Bank  5 USD
          Income:Salary

        2020-03-01 balance Assets:Bank:Savings  0 USD
        """)
    assert txn.flag == FLAG_WARNING
    assert [p.flag for p in txn.postings] == [None, None]


def test_subaccount_uses_later_of_own_and_parent_balance():
    [txn] = load_txns("""
        2020-02-01 balance Assets:Bank  0 USD

        2020-02-15 ! "Interest"
          Assets:Bank:Savings  1 USD
          Income:Salary

        2020-03-01 balance Assets:Bank:Savings  1 USD
        """)
    assert txn.flag == FLAG_OKAY
    assert [p.flag for p in txn.postings] == [FLAG_OKAY, None]


def test_balance_is_per_currency():
    [txn] = load_txns("""
        2020-02-01 ! "Euro lunch"
          Assets:Cash  -10 EUR
          Expenses:Food

        2020-03-01 balance Assets:Cash  0 USD
        """)
    assert txn.flag == FLAG_WARNING
    assert [p.flag for p in txn.postings] == [None, None]


def test_covered_warning_flags_are_cleared():
    [txn] = load_txns("""
        2020-02-01 ! "Lunch"
          ! Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)
    assert txn.flag == FLAG_OKAY
    assert [p.flag for p in txn.postings] == [FLAG_OKAY, None]


def test_special_transaction_flags_are_preserved():
    [txn] = load_txns(f"""
        2020-02-01 {FLAG_TRANSFER} "Transfer"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)
    assert txn.flag == FLAG_TRANSFER
    assert [p.flag for p in txn.postings] == [None, None]


def test_padding_transactions_load_cleanly():
    [padding, spend] = load_txns("""
        2020-01-02 pad Assets:Bank Equity:Opening
        2020-02-01 balance Assets:Bank  100 USD

        2020-02-15 * "Spend"
          Assets:Bank  -10 USD
          Expenses:Food
        """)
    assert padding.flag == FLAG_PADDING
    assert spend.flag == FLAG_WARNING


@pytest.mark.parametrize("flag", [FLAG_OKAY, FLAG_WARNING])
def test_unchanged_entries_keep_identity(flag):
    entries, options_map = load(
        f"""
        2020-01-15 * "Unrelated"
          Assets:Bank  -10 USD
          Expenses:Food

        2020-02-01 {flag} "Lunch"
          * Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """,
        plugin=False,
    )
    new_entries, errors = flag_balanced(entries, options_map)
    assert errors == []
    [old_unrelated, old_lunch] = filter_txns(entries)
    [new_unrelated, new_lunch] = filter_txns(new_entries)
    assert new_unrelated is old_unrelated
    assert (new_lunch is old_lunch) == (flag == FLAG_OKAY)
    assert new_lunch.flag == FLAG_OKAY


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
    [old_txn] = filter_txns(entries)
    [new_txn] = filter_txns(new_entries)
    assert old_txn.flag == FLAG_WARNING
    assert new_txn.flag == FLAG_OKAY


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
