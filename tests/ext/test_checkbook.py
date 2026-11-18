import datetime
from decimal import Decimal

from beancount.core.data import filter_txns
from fava.application import create_app
from fava.beans.funcs import hash_entry
from fava.core import FavaLedger

from beancount_sg.builders import A, P, T
from beancount_sg.ext.checkbook import SPLIT, checkbook_rows

ROOTS = frozenset({"Assets", "Liabilities"})


def check(**kwargs):
    defaults = {
        "payee": "Plumber",
        "narration": "CHECK #1042",
        "meta": {"check-no": "1042"},
        "postings": [
            P("Assets:Checking", A("-250.00", "USD")),
            P("Expenses:Home", A("250.00", "USD")),
        ],
    }
    return T("2024-03-04", **{**defaults, **kwargs})


def rows(*entries):
    return checkbook_rows(entries, ROOTS)


def test_check_row():
    txn = check()
    [row] = rows(txn)
    assert row.entry_hash == hash_entry(txn)
    assert row.date == datetime.date(2024, 3, 4)
    assert row.check_no == 1042
    assert (row.payee, row.narration) == ("Plumber", "CHECK #1042")
    assert (row.account, row.category) == ("Assets:Checking", "Expenses:Home")
    assert row.amount == A("250.00", "USD")


def test_only_transactions_with_check_numbers_are_listed():
    assert len(rows(check(), check(meta={}))) == 1


def test_check_number_stored_as_a_number():
    [row] = rows(check(meta={"check-no": Decimal(1042)}))
    assert row.check_no == 1042


def test_split_category():
    [row] = rows(
        check(
            postings=[
                P("Assets:Checking", A("-250.00", "USD")),
                P("Expenses:Home", A("200.00", "USD")),
                P("Expenses:Garden", A("50.00", "USD")),
            ]
        )
    )
    assert row.category == SPLIT


def test_check_from_a_liability_account_in_any_posting_order():
    [row] = rows(
        check(
            postings=[
                P("Expenses:Home", A("250.00", "USD")),
                P("Liabilities:HELOC", A("-250.00", "USD")),
            ]
        )
    )
    assert (row.account, row.category) == ("Liabilities:HELOC", "Expenses:Home")


def test_unclear_paying_account_is_left_blank():
    [row] = rows(
        check(
            postings=[
                P("Assets:Checking", A("-200.00", "USD")),
                P("Assets:Savings", A("-50.00", "USD")),
                P("Expenses:Home", A("250.00", "USD")),
            ]
        )
    )
    assert (row.account, row.category, row.amount) == (None, SPLIT, None)


def test_long_text_is_truncated():
    [row] = rows(check(payee="A" * 40))
    assert row.payee == "A" * 29 + "..."


LEDGER = """
option "title" "Test"
2020-01-01 custom "fava-extension" "beancount_sg.ext.checkbook"
2020-01-01 open Assets:Checking
2020-01-01 open Expenses:Home

2024-03-04 * "Plumber" "CHECK #1042"
  check-no: "1042"
  Assets:Checking  -250.00 USD
  Expenses:Home
"""


def test_report_page_links_each_check_to_its_transaction(tmp_path):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(LEDGER)
    response = create_app([ledger], load=True).test_client().get("/test/extension/Checkbook/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    txn_hash = hash_entry(next(filter_txns(FavaLedger(str(ledger)).all_entries)))
    assert f'<a href="#context-{txn_hash}">2024-03-04</a>' in body
    assert '<a href="/test/account/Assets:Checking/">Assets:Checking</a>' in body
    assert '<td class="num" data-sort-value="250.00">250.00 USD</td>' in body
