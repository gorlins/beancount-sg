import pytest
from beancount.core.flags import FLAG_OKAY

from beancount_sg.testing import load_txns

PLUGIN = ("beancount_sg.plugins.link_bills", "Liabilities:Bills")


def test_bill_and_payment_in_same_month_are_linked():
    bill, payment = load_txns(
        """
        2020-01-05 * "Electric bill"
          Liabilities:Bills:Electric  -80 USD
          Expenses:Utilities

        2020-01-25 * "Pay electric"
          Liabilities:Bills:Electric   80 USD
          Assets:Checking
        """,
        [PLUGIN],
    )
    assert bill.links == payment.links == {"x-Electric-202001"}
    assert bill.postings[0].flag == payment.postings[0].flag == FLAG_OKAY


def test_partial_payments_are_linked():
    txns = load_txns(
        """
        2020-01-05 * "Electric bill"
          Liabilities:Bills:Electric  -80 USD
          Expenses:Utilities

        2020-01-10 * "Pay electric"
          Liabilities:Bills:Electric   50 USD
          Assets:Checking

        2020-01-25 * "Pay electric"
          Liabilities:Bills:Electric   30 USD
          Assets:Checking
        """,
        [PLUGIN],
    )
    assert all(txn.links == {"x-Electric-202001"} for txn in txns)


def test_payment_in_another_month_is_not_linked():
    txns = load_txns(
        """
        2020-01-05 * "Electric bill"
          Liabilities:Bills:Electric  -80 USD
          Expenses:Utilities

        2020-02-01 * "Pay electric"
          Liabilities:Bills:Electric   80 USD
          Assets:Checking
        """,
        [PLUGIN],
    )
    assert all(not txn.links for txn in txns)
    assert all(txn.postings[0].flag is None for txn in txns)


def test_requires_an_account():
    with pytest.raises(AssertionError, match="requires an account"):
        load_txns("", ["beancount_sg.plugins.link_bills"])
