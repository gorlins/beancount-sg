import pytest
from beancount.core.data import Open
from beancount.core.flags import FLAG_WARNING

from beancount_sg.testing import load, load_txns, posting_flags

LEDGER = """
    2020-01-01 * "Lunch"
      ! Assets:Cash  -10 USD
      Expenses:Food
    """


def test_load_opens_accounts_automatically():
    entries, _ = load(LEDGER)
    assert {e.account for e in entries if isinstance(e, Open)} == {"Assets:Cash", "Expenses:Food"}


def test_load_raises_on_errors():
    with pytest.raises(AssertionError, match="Assets:Cash"):
        load(LEDGER, auto_open=False)


def test_load_txns_and_posting_flags():
    txn = load_txns(LEDGER)[0]
    assert txn.narration == "Lunch"
    assert posting_flags(txn) == [FLAG_WARNING, None]
