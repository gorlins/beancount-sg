import pytest
from beancount.core.flags import FLAG_OKAY

from beancount_sg.testing import load_txns

PLUGIN = ("beancount_sg.plugins.link_transfers", "Assets:Transfers")


def test_same_day_transfer_is_linked():
    out, inn = load_txns(
        """
        2020-01-15 * "To savings"
          Assets:Checking  -100.00 USD
          Assets:Transfers

        2020-01-15 * "From checking"
          Assets:Savings    100.00 USD
          Assets:Transfers
        """,
        [PLUGIN],
    )
    assert out.links == inn.links == {"x-Transfers-20200115-100"}
    assert out.postings[1].flag == inn.postings[1].flag == FLAG_OKAY


@pytest.mark.parametrize(("date", "amount"), [("2020-01-16", "100.00"), ("2020-01-15", "99.00")])
def test_different_day_or_amount_is_not_linked(date, amount):
    txns = load_txns(
        f"""
        2020-01-15 * "To savings"
          Assets:Checking  -100.00 USD
          Assets:Transfers

        {date} * "From checking"
          Assets:Savings    {amount} USD
          Assets:Transfers
        """,
        [PLUGIN],
    )
    assert all(not txn.links for txn in txns)


def test_requires_an_account():
    with pytest.raises(AssertionError, match="requires an account"):
        load_txns("", ["beancount_sg.plugins.link_transfers"])
