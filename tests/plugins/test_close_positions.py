import datetime
import textwrap

import pytest
from beancount.core.data import Balance, Close, filter_txns

from beancount_sg.builders import A
from beancount_sg.plugins.close_positions import close_positions
from beancount_sg.testing import load

PLUGIN = "beancount_sg.plugins.close_positions"

BUY = """
    2018-01-10 * "Buy calls"
      Assets:Options:QQQC  2 QQQC {2.70 USD}
      Assets:Options:SPYC  1 SPYC {1.00 USD}
      Assets:Cash
    """


def load_closed(ledger: str):
    entries, _ = load(textwrap.dedent(BUY) + textwrap.dedent(ledger), [PLUGIN])
    balances = [(e.date, e.account, e.amount) for e in entries if isinstance(e, Balance)]
    closes = [(e.date, e.account) for e in entries if isinstance(e, Close)]
    return entries, balances, closes


def test_closing_posting_adds_balance_and_close_next_day():
    _, balances, closes = load_closed("""
        2018-02-16 * "Sell calls"
          Assets:Options:QQQC  -2 QQQC {2.70 USD} @ 5.31 USD
            closing: TRUE
          Assets:Cash  10.62 USD
          Income:PnL
        """)
    next_day = datetime.date(2018, 2, 17)
    assert balances == [(next_day, "Assets:Options:QQQC", A(0, "QQQC"))]
    assert closes == [(next_day, "Assets:Options:QQQC")]


def test_account_holding_several_commodities_gets_balance_but_no_close():
    _, balances, closes = load_closed("""
        2018-01-10 * "Buy into a shared account"
          Assets:Brokerage  3 VTI {200.00 USD}
          Assets:Brokerage  5 BND {70.00 USD}
          Assets:Cash

        2018-02-16 * "Sell all VTI"
          Assets:Brokerage  -3 VTI {200.00 USD} @ 210.00 USD
            closing: TRUE
          Assets:Cash  630.00 USD
          Income:PnL

        2018-03-01 * "Still trading BND"
          Assets:Brokerage  -1 BND {70.00 USD} @ 71.00 USD
          Assets:Cash  71.00 USD
          Income:PnL
        """)
    assert balances == [(datetime.date(2018, 2, 17), "Assets:Brokerage", A(0, "VTI"))]
    assert closes == []


def test_position_left_open_is_a_balance_error():
    with pytest.raises(AssertionError, match="Balance failed for 'Assets:Options:QQQC'"):
        load_closed("""
            2018-02-16 * "Sell some calls"
              Assets:Options:QQQC  -1 QQQC {2.70 USD} @ 5.31 USD
                closing: TRUE
              Assets:Cash  5.31 USD
              Income:PnL
            """)


@pytest.mark.parametrize("meta", [{}, {"closing": "FALSE"}])
def test_postings_not_marked_closing_add_nothing(meta):
    meta_lines = "".join(f"\n    {key}: {value}" for key, value in meta.items())
    _, balances, closes = load_closed(f"""
2018-02-16 * "Sell calls"
  Assets:Options:QQQC  -2 QQQC {{2.70 USD}} @ 5.31 USD{meta_lines}
  Assets:Cash  10.62 USD
  Income:PnL
""")
    assert balances == closes == []


def test_every_closing_posting_in_a_transaction_is_handled():
    _, balances, closes = load_closed("""
        2018-02-16 * "Sell all calls"
          Assets:Options:QQQC  -2 QQQC {2.70 USD} @ 5.31 USD
            closing: TRUE
          Assets:Options:SPYC  -1 SPYC {1.00 USD} @ 2.00 USD
            closing: TRUE
          Assets:Cash  12.62 USD
          Income:PnL
        """)
    assert [account for _, account, _ in balances] == ["Assets:Options:QQQC", "Assets:Options:SPYC"]
    assert [account for _, account in closes] == ["Assets:Options:QQQC", "Assets:Options:SPYC"]


def test_closing_postings_to_one_account_add_one_balance_and_close():
    _, balances, closes = load_closed("""
        2018-02-16 * "Sell calls in two fills"
          Assets:Options:QQQC  -1 QQQC {2.70 USD} @ 5.31 USD
            closing: TRUE
          Assets:Options:QQQC  -1 QQQC {2.70 USD} @ 5.30 USD
            closing: TRUE
          Assets:Cash  10.61 USD
          Income:PnL
        """)
    assert len(balances) == len(closes) == 1


def test_existing_balance_and_close_are_not_duplicated():
    _, balances, closes = load_closed("""
        2018-02-16 * "Sell calls"
          Assets:Options:QQQC  -2 QQQC {2.70 USD} @ 5.31 USD
            closing: TRUE
          Assets:Cash  10.62 USD
          Income:PnL

        2018-02-17 balance Assets:Options:QQQC  0 QQQC
        2018-02-20 close Assets:Options:QQQC
        """)
    assert balances == [(datetime.date(2018, 2, 17), "Assets:Options:QQQC", A(0, "QQQC"))]
    assert closes == [(datetime.date(2018, 2, 20), "Assets:Options:QQQC")]


def test_metadata_is_kept_and_added_directives_point_at_the_posting():
    entries, _, _ = load_closed("""
        2018-02-16 * "Sell calls"
          Assets:Options:QQQC  -2 QQQC {2.70 USD} @ 5.31 USD
            closing: TRUE
          Assets:Cash  10.62 USD
          Income:PnL
        """)
    posting = list(filter_txns(entries))[-1].postings[0]
    assert posting.meta["closing"] is True
    added = [e for e in entries if isinstance(e, Balance | Close)]
    assert {e.meta["lineno"] for e in added} == {posting.meta["lineno"]}


@pytest.mark.parametrize(
    "posting",
    [
        "Assets:Cash  -100.00 USD",  # no position at all
        "Assets:Options:QQQC  1 QQQC {2.70 USD}",  # a purchase, not a sale
        "Assets:Cash  -100.00 EUR @ 1.10 USD",  # a conversion at a price, not at cost
    ],
)
def test_closing_posting_that_is_not_a_sale_is_an_error(posting):
    entries, options_map = load(
        textwrap.dedent(BUY)
        + f"""
2018-02-16 * "Not a sale"
  {posting}
    closing: TRUE
  Income:Other
"""
    )
    new_entries, errors = close_positions(entries, options_map)
    [error] = errors
    assert "only for sales of a position held at cost" in error.message
    marked = list(filter_txns(entries))[-1].postings[0]
    assert error.source["lineno"] == marked.meta["lineno"]
    assert not [e for e in new_entries if isinstance(e, Balance | Close)]


def test_not_a_sale_is_reported_when_loading():
    with pytest.raises(AssertionError, match="only for sales of a position held at cost"):
        load_closed("""
            2018-02-16 * "Withdraw"
              Assets:Cash  -100.00 USD
                closing: TRUE
              Expenses:Misc
            """)
