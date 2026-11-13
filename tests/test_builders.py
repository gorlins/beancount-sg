import datetime
from decimal import Decimal

import pytest
from beancount.core.amount import Amount
from beancount.core.data import Balance, Transaction, filter_txns
from beancount.core.flags import FLAG_OKAY, FLAG_WARNING
from beancount.parser import printer

from beancount_sg.builders import A, B, P, T
from beancount_sg.testing import load


@pytest.mark.parametrize("number", ["-10.50", -10, Decimal("-10.50")])
def test_amount(number):
    assert A(number, "USD") == Amount(Decimal(number), "USD")


def test_amount_parses_thousands_separators():
    assert A("1,234.50", "USD") == Amount(Decimal("1234.50"), "USD")


def test_amount_rejects_float():
    with pytest.raises(TypeError, match="float"):
        A(10.5, "USD")


def test_transaction_defaults():
    txn = T(datetime.date(2020, 2, 1))
    assert txn == Transaction(
        meta={},
        date=datetime.date(2020, 2, 1),
        flag=FLAG_OKAY,
        payee=None,
        narration="",
        tags=frozenset(),
        links=frozenset(),
        postings=[],
    )


def test_transaction_fields():
    posting = P("Assets:Cash", A(-10, "USD"))
    txn = T(
        "2020-02-01",
        flag=FLAG_WARNING,
        payee="Cafe",
        narration="Lunch",
        tags=["food", "work"],
        links={"receipt-1"},
        postings=(posting,),
        meta={"source": "import"},
    )
    assert txn.date == datetime.date(2020, 2, 1)
    assert txn.flag == FLAG_WARNING
    assert txn.payee == "Cafe"
    assert txn.narration == "Lunch"
    assert txn.tags == frozenset({"food", "work"})
    assert txn.links == frozenset({"receipt-1"})
    assert txn.postings == [posting]
    assert txn.meta == {"source": "import"}


def test_transaction_arguments_after_date_are_keyword_only():
    with pytest.raises(TypeError):
        T("2020-02-01", FLAG_OKAY)


def test_defaults_are_not_shared_between_calls():
    first, second = T("2020-02-01"), T("2020-02-01")
    first.meta["key"] = "value"
    first.postings.append(P("Assets:Cash"))
    assert second.meta == {}
    assert second.postings == []


def test_meta_and_postings_are_copied():
    meta = {"key": "value"}
    postings = [P("Assets:Cash")]
    txn = T("2020-02-01", meta=meta, postings=postings)
    assert txn.meta == meta and txn.meta is not meta
    assert txn.postings == postings and txn.postings is not postings


def test_datetime_is_converted_to_date():
    txn = T(datetime.datetime(2020, 2, 1, 12, 30))
    assert txn.date == datetime.date(2020, 2, 1)
    assert type(txn.date) is datetime.date


def test_rejects_invalid_date_string():
    with pytest.raises(ValueError):
        T("2020-02-30")


def test_posting_defaults():
    posting = P("Assets:Cash", A(-10, "USD"))
    assert posting.account == "Assets:Cash"
    assert posting.units == A(-10, "USD")
    assert posting.cost is None
    assert posting.price is None
    assert posting.flag is None
    assert posting.meta == {}


def test_posting_fields():
    posting = P(
        "Assets:Cash",
        A(-10, "USD"),
        price=A("0.9", "EUR"),
        flag=FLAG_WARNING,
        meta={"key": "value"},
    )
    assert posting.price == A("0.9", "EUR")
    assert posting.flag == FLAG_WARNING
    assert posting.meta == {"key": "value"}


def test_balance():
    balance = B("2020-03-01", "Assets:Cash", A(-10, "USD"))
    assert balance == Balance(
        meta={},
        date=datetime.date(2020, 3, 1),
        account="Assets:Cash",
        amount=A(-10, "USD"),
        tolerance=None,
        diff_amount=None,
    )


def test_built_entries_round_trip_through_beancount():
    entries = [
        T(
            "2020-02-01",
            flag=FLAG_WARNING,
            payee="Cafe",
            narration="Lunch",
            tags=["food"],
            postings=[
                P("Assets:Cash", A("-10.50", "USD"), flag=FLAG_OKAY),
                P("Expenses:Food"),  # units inferred by Beancount
            ],
        ),
        B("2020-03-01", "Assets:Cash", A("-10.50", "USD")),
    ]
    loaded, _ = load("\n".join(printer.format_entry(entry) for entry in entries))
    [txn] = filter_txns(loaded)
    assert (txn.date, txn.flag, txn.payee, txn.narration, txn.tags) == (
        datetime.date(2020, 2, 1),
        FLAG_WARNING,
        "Cafe",
        "Lunch",
        frozenset({"food"}),
    )
    assert [(p.account, p.units, p.flag) for p in txn.postings] == [
        ("Assets:Cash", A("-10.50", "USD"), FLAG_OKAY),
        ("Expenses:Food", A("10.50", "USD"), None),
    ]
    assert [e for e in loaded if isinstance(e, Balance)][0].amount == A("-10.50", "USD")
