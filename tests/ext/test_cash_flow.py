import datetime
import html
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from fava.application import create_app

import beancount_sg.ext.cash_flow as cash_flow_ext

from .test_cash_flow_statement import LEDGER as STATEMENT_LEDGER

ENABLE = 'custom "fava-extension" "beancount_sg.ext.cash_flow"'
LEDGER = (
    f"""
option "title" "Test"
option "operating_currency" "USD"
2020-01-01 {ENABLE}
"""
    + STATEMENT_LEDGER
)


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """Today, for the report: late 2024 unless a test changes it."""
    day = datetime.date(2024, 9, 30)
    monkeypatch.setattr(cash_flow_ext, "local_today", lambda: day)
    return day


def page(tmp_path, text=LEDGER, query=""):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(text)
    response = (
        create_app([ledger], load=True).test_client().get(f"/test/extension/CashFlow/{query}")
    )
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(body):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))


def panel(body, title):
    start = body.index(f"<h3>{title}")
    return text(body[start : body.index("</section>", start)])


def test_defaults_to_this_year_to_date(tmp_path):
    body = text(page(tmp_path))
    assert "2024-01-01 to 2024-09-30, in USD." in body


def test_cards(tmp_path):
    body = page(tmp_path, query="?time=2024")
    cards = text(
        body[body.index('<div class="cf-cards">') : body.index('<div class="cf-columns">')]
    )
    assert "Net change in cash +2,900 10,000 → 12,900" in cards
    assert "operating activities +4,400" in cards
    assert "investing activities −1,000" in cards
    assert "financing activities −500" in cards
    # Money in is green, money out red.
    assert '<span class="cf-good">+4,400</span>' in body
    assert '<span class="cf-bad">−1,000</span>' in body


def test_statement(tmp_path):
    found = panel(page(tmp_path, query="?time=2024"), "Statement")
    assert (
        "Operating activities Income:Salary +5,000 Expenses:Food −400 Expenses:Housing −200 "
        "Net cash from operating activities +4,400"
    ) in found
    assert (
        "Investing activities Assets:Brokerage −1,000 Net cash from investing activities −1,000"
        in found
    )
    assert "Financing activities Liabilities:Mortgage −500" in found
    assert found.strip().endswith("Net change in cash +2,900")


def test_reconciliation(tmp_path):
    found = panel(page(tmp_path, query="?time=2024"), "Cash &amp; cash equivalents")
    assert "Assets:Bank:Checking 10,000 12,900 Total 10,000 12,900" in found
    assert (
        "Cash at the start 10,000 Net change from activities +2,900 Cash at the end 12,900" in found
    )
    assert "Change in value" not in found


def test_lines_link_to_their_accounts_for_the_period(tmp_path):
    body = page(tmp_path, query="?time=2024")
    [href] = re.findall(r'<a href="([^"]+)">Assets:Brokerage</a>', body)
    url = urlsplit(html.unescape(href))
    assert unquote(url.path) == "/test/account/Assets:Brokerage/"
    assert parse_qs(url.query)["time"] == ["2024-01-01 - 2024-12-31"]


def test_chart(tmp_path):
    body = page(tmp_path, query="?time=2024&interval=quarter")
    [data] = re.findall(
        r'<svelte-component type="charts"><script type="application/json">(.*?)</script>', body
    )
    [chart] = json.loads(data)
    assert chart["label"] == "Cash flows by activity (Quarterly)"
    assert [bar["date"] for bar in chart["data"]] == [
        "2024-03-31",
        "2024-06-30",
        "2024-09-30",
        "2024-12-31",
    ]
    assert chart["data"][0]["account_balances"] == {
        "Operating": {"USD": "4600"},
        "Investing": {"USD": "-1000"},
        "Financing": {"USD": "0"},
    }
    [links] = re.findall(
        r'<script type="application/json" id="cash-flow-chart-links">(.*?)</script>', body
    )
    assert set(json.loads(links)) == {"Operating", "Investing", "Financing"}


def test_filters_apply(tmp_path):
    body = page(tmp_path, query="?time=2024&filter=-Groceries")
    assert "Expenses:Food −100" in panel(body, "Statement")


def test_classification(tmp_path):
    body = text(
        page(
            tmp_path,
            LEDGER.replace(
                "2020-01-01 open Assets:Brokerage",
                '2020-01-01 open Assets:Brokerage\n  cash-flow-role: "investing"',
            ),
        )
    )
    assert "Assets:Bank:Checking cash default, from its name and type" in body
    assert "Assets:Brokerage investing declared" in body
    assert "Liabilities:CreditCard financing default" in body


def test_unknown_role_is_reported(tmp_path):
    ledger = LEDGER.replace(
        "2020-01-01 open Assets:Brokerage",
        '2020-01-01 open Assets:Brokerage\n  cash-flow-role: "invsting"',
    )
    assert "Assets:Brokerage: unknown cash-flow-role 'invsting', using the default" in text(
        page(tmp_path, ledger)
    )


def test_without_an_operating_currency(tmp_path):
    body = text(page(tmp_path, LEDGER.replace('option "operating_currency" "USD"\n', "")))
    assert "Set an operating_currency option" in body
