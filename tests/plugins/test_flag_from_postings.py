import pytest
from beancount.core.data import filter_txns
from beancount.core.flags import FLAG_OKAY, FLAG_PADDING, FLAG_TRANSFER, FLAG_WARNING

from beancount_sg.plugins.flag_from_postings import flag_from_postings
from beancount_sg.testing import load, load_txns

PLUGIN = "beancount_sg.plugins.flag_from_postings"


def load_flagged(ledger: str):
    return load_txns(ledger, [PLUGIN])


@pytest.mark.parametrize("txn_flag", [FLAG_OKAY, FLAG_WARNING])
def test_any_warning_posting_flags_transaction_warning(txn_flag):
    txn = load_flagged(f"""
        2020-02-01 {txn_flag} "Withdraw"
          * Assets:Bank  -20 USD
          ! Assets:Cash   20 USD
        """)[0]
    assert txn.flag == FLAG_WARNING


@pytest.mark.parametrize("txn_flag", [FLAG_OKAY, FLAG_WARNING])
def test_all_okay_postings_flag_transaction_okay(txn_flag):
    txn = load_flagged(f"""
        2020-02-01 {txn_flag} "Withdraw"
          * Assets:Bank  -20 USD
          * Assets:Cash   20 USD
        """)[0]
    assert txn.flag == FLAG_OKAY


def test_unflagged_postings_are_ignored():
    txn = load_flagged("""
        2020-02-01 ! "Lunch"
          * Assets:Cash  -10 USD
          Expenses:Food
        """)[0]
    assert txn.flag == FLAG_OKAY


def test_no_flagged_postings_flags_transaction_okay():
    txn = load_flagged("""
        2020-02-01 ! "Lunch"
          Assets:Cash  -10 USD
          Expenses:Food
        """)[0]
    assert txn.flag == FLAG_OKAY


def test_special_posting_flags_are_ignored():
    txn = load_flagged(f"""
        2020-02-01 ! "Lunch"
          {FLAG_TRANSFER} Assets:Cash  -10 USD
          Expenses:Food
        """)[0]
    assert txn.flag == FLAG_OKAY


def test_special_transaction_flag_is_preserved():
    txn = load_flagged(f"""
        2020-02-01 {FLAG_TRANSFER} "Transfer"
          ! Assets:Bank  -20 USD
          Assets:Cash     20 USD
        """)[0]
    assert txn.flag == FLAG_TRANSFER


def test_posting_flags_are_not_changed():
    txn = load_flagged("""
        2020-02-01 * "Withdraw"
          ! Assets:Bank  -20 USD
          Assets:Cash     20 USD
        """)[0]
    assert [p.flag for p in txn.postings] == [FLAG_WARNING, None]


def test_padding_transactions_load_cleanly():
    padding, _ = load_flagged("""
        2020-01-02 pad Assets:Bank Equity:Opening
        2020-02-01 balance Assets:Bank  100 USD

        2020-02-15 * "Spend"
          Assets:Bank  -10 USD
          Expenses:Food
        """)
    assert padding.flag == FLAG_PADDING


def test_with_flag_balanced():
    # flag_balanced sets the posting flags; flag_from_postings, listed after it, rolls them up.
    covered, uncovered = load_txns(
        """
        2020-02-01 ! "Covered"
          Assets:Bank  -20 USD
          Assets:Cash   20 USD

        2020-03-01 balance Assets:Bank  -20 USD

        2020-03-15 * "Uncovered"
          Assets:Bank  -20 USD
          Assets:Cash   20 USD
        """,
        ["beancount_sg.plugins.flag_balanced", PLUGIN],
    )
    assert covered.flag == FLAG_OKAY
    assert [p.flag for p in covered.postings] == [FLAG_OKAY, None]
    assert uncovered.flag == FLAG_WARNING
    assert [p.flag for p in uncovered.postings] == [FLAG_WARNING, None]


def test_unchanged_entries_keep_identity():
    entries, options_map = load("""
        2020-02-01 * "Okay"
          * Assets:Cash  -10 USD
          Expenses:Food

        2020-02-02 ! "Warning"
          ! Assets:Cash  -10 USD
          Expenses:Food

        2020-02-03 ! "Needs change"
          * Assets:Cash  -10 USD
          Expenses:Food
        """)
    new_entries, errors = flag_from_postings(entries, options_map)
    assert errors == []
    old_okay, old_warning, old_change = filter_txns(entries)
    new_okay, new_warning, new_change = filter_txns(new_entries)
    assert new_okay is old_okay
    assert new_warning is old_warning
    assert new_change is not old_change
    assert old_change.flag == FLAG_WARNING
    assert new_change.flag == FLAG_OKAY
