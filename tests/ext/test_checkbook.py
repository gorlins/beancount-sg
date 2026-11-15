import datetime
import json
import re
from decimal import Decimal

from fava.application import create_app

from beancount_sg.builders import A, P, T
from beancount_sg.ext.checkbook import SPLIT, checkbook_table

ROOTS = frozenset({"Assets", "Liabilities"})


def check(**kwargs):
    defaults = {
        "payee": "Plumber",
        "narration": "CHECK #1042",
        "meta": {"check_no": "1042"},
        "postings": [
            P("Assets:Checking", A("-250.00", "USD")),
            P("Expenses:Home", A("250.00", "USD")),
        ],
    }
    return T("2024-03-04", **{**defaults, **kwargs})


def rows(*entries):
    """The table's rows as dicts by column name."""
    table = checkbook_table(entries, ROOTS)
    names = [column.name for column in table.types]
    return [dict(zip(names, row, strict=True)) for row in table.rows]


def test_check_row():
    [row] = rows(check())
    assert row["date"] == datetime.date(2024, 3, 4)
    assert row["check_no"] == 1042
    assert (row["payee"], row["narration"]) == ("Plumber", "CHECK #1042")
    assert (row["account"], row["category"]) == ("Assets:Checking", "Expenses:Home")
    assert (row["amount"].number, row["amount"].currency) == (Decimal("250.00"), "USD")


def test_only_transactions_with_check_numbers_are_listed():
    assert len(rows(check(), check(meta={}))) == 1


def test_check_number_stored_as_a_number():
    [row] = rows(check(meta={"check_no": Decimal(1042)}))
    assert row["check_no"] == 1042


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
    assert row["category"] == SPLIT


def test_check_from_a_liability_account_in_any_posting_order():
    [row] = rows(
        check(
            postings=[
                P("Expenses:Home", A("250.00", "USD")),
                P("Liabilities:HELOC", A("-250.00", "USD")),
            ]
        )
    )
    assert (row["account"], row["category"]) == ("Liabilities:HELOC", "Expenses:Home")


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
    assert (row["account"], row["category"], row["amount"]) == (None, SPLIT, None)


def test_long_text_is_truncated():
    [row] = rows(check(payee="A" * 40))
    assert row["payee"] == "A" * 29 + "..."


def test_report_page_renders_in_fava(tmp_path):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(
        """
option "title" "Test"
2020-01-01 custom "fava-extension" "beancount_sg.ext.checkbook"
2020-01-01 open Assets:Checking
2020-01-01 open Expenses:Home

2024-03-04 * "Plumber" "CHECK #1042"
  check_no: "1042"
  Assets:Checking  -250.00 USD
  Expenses:Home
"""
    )
    client = create_app([ledger], load=True).test_client()
    response = client.get("/test/extension/Checkbook/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    table = json.loads(re.search(r'application/json">(.*?)</script>', body, re.S).group(1))
    assert table["rows"] == [
        [
            "2024-03-04",
            1042,
            "Plumber",
            "Assets:Checking",
            "Expenses:Home",
            "CHECK #1042",
            {"currency": "USD", "number": "250.00"},
        ]
    ]
