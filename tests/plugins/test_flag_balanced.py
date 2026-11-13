import pytest
from beancount.core.data import filter_txns
from beancount.core.flags import FLAG_OKAY, FLAG_PADDING, FLAG_TRANSFER, FLAG_WARNING

from beancount_sg.plugins.flag_balanced import flag_balanced
from beancount_sg.testing import load, load_txns, posting_flags

PLUGIN = "beancount_sg.plugins.flag_balanced"


def load_flagged(ledger: str):
    return load_txns(ledger, [PLUGIN])


def test_transaction_before_balance_is_okay():
    txn = load_flagged("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)[0]
    assert txn.flag == FLAG_OKAY
    assert posting_flags(txn) == [FLAG_OKAY, None]


def test_transaction_on_balance_date_is_not_covered():
    # A balance assertion checks the balance at the *start* of its date.
    txn = load_flagged("""
        2020-03-01 * "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  0 USD
        """)[0]
    assert txn.flag == FLAG_WARNING
    assert posting_flags(txn) == [FLAG_WARNING, None]


def test_transaction_after_last_balance_is_warning():
    txn = load_flagged("""
        2020-02-01 balance Assets:Cash  0 USD

        2020-03-01 * "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food
        """)[0]
    assert txn.flag == FLAG_WARNING
    assert posting_flags(txn) == [FLAG_WARNING, None]


def test_latest_balance_determines_coverage():
    txn = load_flagged("""
        2020-02-01 balance Assets:Cash  0 USD

        2020-02-15 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)[0]
    assert txn.flag == FLAG_OKAY
    assert posting_flags(txn) == [FLAG_OKAY, None]


def test_mixed_coverage_flags_transaction_warning():
    txn = load_flagged("""
        2020-01-15 balance Liabilities:Card  0 USD

        2020-02-01 * "Pay card from bank"
          Assets:Bank       -50 USD
          Liabilities:Card   50 USD

        2020-03-01 balance Assets:Bank  -50 USD
        """)[0]
    assert txn.flag == FLAG_WARNING
    assert posting_flags(txn) == [FLAG_OKAY, FLAG_WARNING]


def test_multiple_postings_to_same_account():
    txn = load_flagged("""
        2020-02-01 ! "Split lunch"
          Assets:Cash  -6 USD
          Assets:Cash  -4 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)[0]
    assert txn.flag == FLAG_OKAY
    assert posting_flags(txn) == [FLAG_OKAY, FLAG_OKAY, None]


def test_untracked_accounts_are_untouched():
    txn = load_flagged("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Bank  0 USD
        """)[0]
    assert txn.flag == FLAG_WARNING
    assert posting_flags(txn) == [None, None]


def test_untracked_account_does_not_block_okay():
    txn = load_flagged("""
        2020-02-01 ! "Withdraw"
          Assets:Bank  -20 USD
          Assets:Cash   20 USD

        2020-03-01 balance Assets:Bank  -20 USD
        """)[0]
    assert txn.flag == FLAG_OKAY
    assert posting_flags(txn) == [FLAG_OKAY, None]


def test_parent_balance_does_not_cover_subaccount():
    txn = load_flagged("""
        2020-02-01 ! "Interest"
          Assets:Bank:Savings  1 USD
          Income:Interest

        2020-03-01 balance Assets:Bank  1 USD
        """)[0]
    assert txn.flag == FLAG_WARNING
    assert posting_flags(txn) == [None, None]


def test_subaccount_balance_does_not_cover_parent():
    txn = load_flagged("""
        2020-02-01 ! "Deposit"
          Assets:Bank  5 USD
          Income:Salary

        2020-03-01 balance Assets:Bank:Savings  0 USD
        """)[0]
    assert txn.flag == FLAG_WARNING
    assert posting_flags(txn) == [None, None]


def test_balance_is_per_currency():
    txn = load_flagged("""
        2020-02-01 ! "Euro lunch"
          Assets:Cash  -10 EUR
          Expenses:Food

        2020-03-01 balance Assets:Cash  0 USD
        """)[0]
    assert txn.flag == FLAG_WARNING
    assert posting_flags(txn) == [None, None]


def test_covered_warning_flags_are_cleared():
    txn = load_flagged("""
        2020-02-01 ! "Lunch"
          ! Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)[0]
    assert txn.flag == FLAG_OKAY
    assert posting_flags(txn) == [FLAG_OKAY, None]


@pytest.mark.parametrize(
    ("balance", "expected"),
    [
        ("2020-03-01 balance Assets:Cash  -10 USD", FLAG_OKAY),
        ("2020-01-15 balance Assets:Cash  0 USD", FLAG_WARNING),
    ],
)
def test_special_transaction_flag_is_kept_but_postings_are_managed(balance, expected):
    txn = load_flagged(f"""
        2020-02-01 {FLAG_TRANSFER} "Transfer"
          Assets:Cash  -10 USD
          Expenses:Food

        {balance}
        """)[0]
    assert txn.flag == FLAG_TRANSFER
    assert posting_flags(txn) == [expected, None]


def test_padding_transactions_load_cleanly():
    padding, spend = load_flagged("""
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
    entries, options_map = load(f"""
        2020-01-15 * "Unrelated"
          Assets:Bank  -10 USD
          Expenses:Food

        2020-02-01 {flag} "Lunch"
          * Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)
    new_entries, errors = flag_balanced(entries, options_map)
    assert errors == []
    old_unrelated, old_lunch = filter_txns(entries)
    new_unrelated, new_lunch = filter_txns(new_entries)
    assert new_unrelated is old_unrelated
    assert (new_lunch is old_lunch) == (flag == FLAG_OKAY)
    assert new_lunch.flag == FLAG_OKAY


def test_input_list_is_not_mutated():
    entries, options_map = load("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food

        2020-03-01 balance Assets:Cash  -10 USD
        """)
    snapshot = list(entries)
    new_entries, _ = flag_balanced(entries, options_map)
    assert entries == snapshot
    assert list(filter_txns(entries))[0].flag == FLAG_WARNING
    assert list(filter_txns(new_entries))[0].flag == FLAG_OKAY


def test_no_balances_returns_entries_unchanged():
    entries, options_map = load("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food
        """)
    new_entries, errors = flag_balanced(entries, options_map)
    assert new_entries is entries
    assert errors == []
