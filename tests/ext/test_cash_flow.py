import datetime
import html
import json
import re
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from fava.application import create_app

import beancount_sg.ext.cash_flow as cash_flow_ext
from beancount_sg.cash_flow_roles import FINANCING, INVESTING

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


def test_defaults_to_the_last_12_months(tmp_path):
    body = text(page(tmp_path))
    # Today is 2024-09-30: this month and the 11 before.
    assert "2023-10-01 to 2024-09-30, in USD." in body


def cards(body):
    return text(body[body.index('<div class="cf-cards">') : body.index('<div class="cf-columns">')])


def test_cards_have_plain_titles(tmp_path):
    found = cards(page(tmp_path, query="?time=2024"))
    assert "Net income +4,400 income minus spending" in found
    assert "Invested 1,000 put into investments, minus withdrawals" in found
    assert "Debt paid down 500 loan and card payments, minus new borrowing" in found
    assert "Change in cash +2,900 10,000 → 12,900" in found
    # 600 spent in the 12 months up to today: 50 a month, which 12,900 of cash covers 258 times.
    assert "Emergency fund 258.0 months cash ÷ 50 a month" in found


def test_a_zero_total_keeps_the_usual_title():
    assert cash_flow_ext.card(INVESTING, Decimal(0)).title == "Invested"
    assert cash_flow_ext.card(FINANCING, Decimal(0)).title == "Debt paid down"


def test_a_card_for_withdrawing_and_borrowing(tmp_path):
    ledger = LEDGER.replace(
        "Assets:Brokerage  10 VTI {100 USD}", "Assets:Brokerage  -10 USD"
    ).replace("Liabilities:Mortgage  500 USD", "Liabilities:Mortgage  -500 USD")
    found = cards(page(tmp_path, ledger, query="?time=2024"))
    assert "Withdrawn from investments 10" in found
    assert "Borrowed 500" in found


def test_a_time_filter_ends_today(tmp_path):
    # Today is 2024-09-30, so 2024 is year-to-date.
    assert "2024-01-01 to 2024-09-30, in USD." in text(page(tmp_path, query="?time=2024"))


def test_only_net_income_is_colored(tmp_path):
    body = page(tmp_path, query="?time=2024")
    assert '<span class="cf-good">+4,400</span>' in body  # a surplus
    assert '<span class="cf-neutral">1,000</span>' in body  # the Invested card: not bad
    assert '<span class="cf-neutral">+1,000</span>' in body  # the statement's Invested
    assert '<span class="cf-neutral">+500</span>' in body  # and Debt paid down
    deficit = LEDGER.replace("Assets:Bank:Checking  5000 USD", "Assets:Bank:Checking  50 USD")
    assert '<span class="cf-bad">−550</span>' in page(tmp_path, deficit, query="?time=2024")


def test_statement(tmp_path):
    found = panel(page(tmp_path, query="?time=2024"), "Statement")
    # Each section reads in its own direction, like the cards.
    assert (
        "Operating: income (+) and spending (−) Income:Salary +5,000 Expenses:Food −400 "
        "Expenses:Housing −200 Net income +4,400"
    ) in found
    assert (
        "Investing: money put in (+) or taken out (−) Assets:Brokerage +1,000 Invested +1,000"
        in found
    )
    assert (
        "Financing: payments (+) or new borrowing (−) Liabilities:Mortgage +500 Debt paid down +500"
    ) in found
    assert "Change in cash +2,900 Change in cash = net income − invested − debt paid down" in found


def test_reconciliation(tmp_path):
    found = panel(page(tmp_path, query="?time=2024"), "Cash &amp; cash equivalents")
    assert "Assets:Bank:Checking 10,000 12,900 Total 10,000 12,900" in found
    assert (
        "Cash at the start 10,000 Change from net income, investing and debt +2,900 "
        "Cash at the end 12,900" in found
    )
    assert "Change in value" not in found


def test_lines_link_to_their_accounts_for_the_period(tmp_path):
    body = page(tmp_path, query="?time=2024")
    [href] = re.findall(r'<a href="([^"]+)">Assets:Brokerage</a>', body)
    url = urlsplit(html.unescape(href))
    assert unquote(url.path) == "/test/account/Assets:Brokerage/"
    assert parse_qs(url.query)["time"] == ["2024-01-01 - 2024-09-30"]  # up to today


def test_charts(tmp_path):
    body = page(tmp_path, query="?time=2024&interval=quarter")
    assert "<h3>Quarterly</h3>" in body
    [data] = re.findall(
        r'<svelte-component type="charts"><script type="application/json">(.*?)</script>', body
    )
    # One chart per card, to switch between, each in its own direction.
    charts = {chart["label"]: chart["data"] for chart in json.loads(data)}
    assert {
        label: [(bar["date"], bar["balance"]["USD"]) for bar in bars]
        for label, bars in charts.items()
    } == {
        "Net income": [("2024-03-31", "4600"), ("2024-06-30", "0"), ("2024-09-30", "-200")],
        "Invested": [("2024-03-31", "1000"), ("2024-06-30", "0"), ("2024-09-30", "0")],
        "Debt paid down": [("2024-03-31", "0"), ("2024-06-30", "0"), ("2024-09-30", "500")],
        "Change in cash": [("2024-03-31", "3600"), ("2024-06-30", "0"), ("2024-09-30", "-700")],
    }


def sankey(body):
    """The Sankey diagram's ECharts series."""
    [data] = re.findall(
        r'<div class="echart" data-echarts="[^"]+" style="height: 300px">'
        r'<script type="application/json">(.*?)</script>',
        body,
    )
    [series] = json.loads(data)["series"]
    return series


def test_sankey(tmp_path):
    series = sankey(page(tmp_path, query="?time=2024"))
    # Only the accounting totals: into cash, income; out of it, expenses, investing,
    # paying down debt, and what was added to cash.
    assert {(link["source"], link["target"], link["value"]) for link in series["links"]} == {
        ("Income", "Cash", 5000),
        ("Cash", "Expenses", 600),
        ("Cash", "Invested", 1000),
        ("Cash", "Debt paid down", 500),
        ("Cash", "Added to cash", 2900),
    }
    nodes = {node["name"]: node for node in series["data"]}
    assert nodes["Income"]["label"] == {"position": "left", "formatter": "Income 5,000"}
    assert nodes["Invested"]["label"]["formatter"] == "Invested 1,000"
    assert "income_statement" in nodes["Expenses"]["url"]
    assert "balance_sheet" in nodes["Debt paid down"]["url"]
    assert nodes["Added to cash"]["url"] is None


def test_sankey_balances_when_cash_is_used_and_debt_grows(tmp_path):
    ledger = LEDGER.replace("Assets:Bank:Checking  5000 USD", "Assets:Bank:Checking  50 USD")
    ledger = ledger.replace("Liabilities:Mortgage  500 USD", "Liabilities:Mortgage  -500 USD")
    links = {
        (link["source"], link["target"]): link["value"]
        for link in sankey(page(tmp_path, ledger, query="?time=2024"))["links"]
    }
    assert links == {
        ("Income", "Cash"): 50,
        ("Borrowed", "Cash"): 500,
        ("Taken from cash", "Cash"): 1050,
        ("Cash", "Expenses"): 600,
        ("Cash", "Invested"): 1000,
    }
    into = sum(value for (_, target), value in links.items() if target == "Cash")
    assert into == sum(value for (source, _), value in links.items() if source == "Cash")


def test_the_echarts_helper_is_served(tmp_path):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(LEDGER)
    client = create_app([ledger], load=True).test_client()
    response = client.get("/test/extension/CashFlow/echarts.js")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"
    assert "export async function renderECharts" in response.get_data(as_text=True)


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
    assert (
        "Assets:Brokerage: cash-flow-role 'invsting' isn't one of"
        " cash, operating, investing, financing; it's ignored" in text(page(tmp_path, ledger))
    )


def test_without_an_operating_currency(tmp_path):
    body = text(page(tmp_path, LEDGER.replace('option "operating_currency" "USD"\n', "")))
    assert "Set an operating_currency option" in body
