import pytest
from beancount.core.flags import FLAG_OKAY

from beancount_sg.testing import load_txns

PLUGIN = ("beancount_sg.plugins.link_transfers", "Assets:Transfers")


def load_transfers(out_date: str, in_date: str, in_amount: str = "100.00"):
    return load_txns(
        f"""
        {out_date} * "To savings"
          Assets:Checking  -100.00 USD
          Assets:Transfers

        {in_date} * "From checking"
          Assets:Savings    {in_amount} USD
          Assets:Transfers
        """,
        [PLUGIN],
    )


@pytest.mark.parametrize(
    ("out_date", "in_date", "link"),
    [
        ("2020-01-15", "2020-01-15", "x-Transfers-20200115-100"),  # same day
        ("2020-01-13", "2020-01-17", "x-Transfers-2020w02-100"),  # same week
        ("2020-01-17", "2020-01-20", "x-Transfers-2020w03-100"),  # week, shifted 3 days
        ("2020-01-06", "2020-01-24", "x-Transfers-202001-100"),  # same month
        ("2020-01-30", "2020-02-20", "x-Transfers-202002-100"),  # month, shifted 3 days
    ],
)
def test_each_pass_links_transfers(out_date, in_date, link):
    out, inn = load_transfers(out_date, in_date)
    assert out.links == inn.links == {link}
    assert out.postings[1].flag == inn.postings[1].flag == FLAG_OKAY


@pytest.mark.parametrize(
    ("in_date", "in_amount"),
    [("2020-01-15", "99.00"), ("2020-03-15", "100.00")],
)
def test_different_amount_or_distant_date_is_not_linked(in_date, in_amount):
    txns = load_transfers("2020-01-15", in_date, in_amount)
    assert all(not txn.links for txn in txns)
    assert all(txn.postings[1].flag is None for txn in txns)


def test_tighter_window_takes_precedence():
    # All four cancel out within the month, but each same-day pair should be linked on its own.
    txns = load_txns(
        """
        2020-01-15 * "To savings"
          Assets:Checking  -100.00 USD
          Assets:Transfers

        2020-01-15 * "From checking"
          Assets:Savings    100.00 USD
          Assets:Transfers

        2020-01-20 * "To savings"
          Assets:Checking  -100.00 USD
          Assets:Transfers

        2020-01-20 * "From checking"
          Assets:Savings    100.00 USD
          Assets:Transfers
        """,
        [PLUGIN],
    )
    assert [txn.links for txn in txns] == [
        {"x-Transfers-20200115-100"},
        {"x-Transfers-20200115-100"},
        {"x-Transfers-20200120-100"},
        {"x-Transfers-20200120-100"},
    ]


def test_requires_an_account():
    with pytest.raises(AssertionError, match="requires an account"):
        load_txns("", ["beancount_sg.plugins.link_transfers"])
