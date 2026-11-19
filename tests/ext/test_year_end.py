import datetime
import html
import json
import re

import pytest
from fava.application import create_app

import beancount_sg.ext.year_end as year_end_ext

ENABLE = 'custom "fava-extension" "beancount_sg.ext.year_end"'

LEDGER = f"""
option "title" "Test"
option "operating_currency" "USD"
2018-01-01 {ENABLE}

2018-01-01 open Assets:Bank:Checking USD
2018-01-01 open Assets:Brokerage
  cash-flow-role: "investing"
2018-01-01 open Liabilities:CreditCard USD
2018-01-01 open Liabilities:Mortgage USD
2018-01-01 open Equity:Opening
2018-01-01 open Income:Salary USD
2018-01-01 open Expenses:Food:Groceries USD
2018-01-01 open Expenses:Housing:Interest USD

2018-01-01 * "Opening balances"
  Assets:Bank:Checking  10000 USD
  Liabilities:Mortgage  -100000 USD
  Equity:Opening
"""
# A salary, groceries and a mortgage payment every year from 2018 to 2025.
for YEAR in range(2018, 2026):
    LEDGER += f"""
{YEAR}-02-01 * "Salary"
  Assets:Bank:Checking  50000 USD
  Income:Salary

{YEAR}-03-01 * "Groceries"
  Expenses:Food:Groceries  {6000 + 100 * (YEAR - 2018)} USD
  Liabilities:CreditCard

{YEAR}-04-01 * "Mortgage payment"
  Liabilities:Mortgage  5000 USD
  Expenses:Housing:Interest  1000 USD
  Assets:Bank:Checking
"""


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """Today, for the report: mid-2025 unless a test changes it."""
    day = datetime.date(2025, 7, 1)
    monkeypatch.setattr(year_end_ext, "local_today", lambda: day)
    return day


def page(tmp_path, text=LEDGER, query=""):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(text)
    response = (
        create_app([ledger], load=True).test_client().get(f"/test/extension/YearInReview/{query}")
    )
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(body):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))


def metrics_header(body):
    table = body[body.index("<h3>Key metrics</h3>") :]
    return text(table[table.index("<thead>") : table.index("</thead>")]).split()


def test_defaults_to_five_years_ending_this_year(tmp_path):
    body = page(tmp_path)
    assert metrics_header(body) == ["2021", "2022", "2023", "2024", "2025", "(YTD)"]
    assert "2025 is year-to-date, through 2025-07-01" in text(body)


def test_ends_with_the_time_filters_last_year(tmp_path):
    assert metrics_header(page(tmp_path, query="?time=2019")) == ["2018", "2019"]
    assert metrics_header(page(tmp_path, query="?time=2020-2023")) == [
        "2019",
        "2020",
        "2021",
        "2022",
        "2023",
    ]


def test_key_metrics(tmp_path):
    body = text(page(tmp_path, query="?time=2019"))
    # 2018: checking 10000 + 50000 - 6000 (mortgage and interest), mortgage 95000, card 6000.
    assert "Net worth -47000 -4100 Cash 54000 98000 Investments 0 0" in body
    assert "Debt -95000 -90000 Other -6000 -12100 Change -47000 42900" in body
    assert "Income 50000 50000 Expenses 7000 7100 Savings 43000 42900" in body
    assert "Savings rate 86.0% 85.8%" in body
    # Without a positive net worth, the ratios to it aren't meaningful.
    assert "Spending / net worth — —" in body
    assert "Net worth in years of spending — —" in body
    assert "Cash in months of spending 92.6 165.6" in body


def test_spending_ratios_with_a_positive_net_worth(tmp_path):
    ledger = LEDGER.replace("Liabilities:Mortgage  -100000 USD", "Liabilities:Mortgage  -20000 USD")
    body = text(page(tmp_path, ledger, query="?time=2019"))
    # 2018 ends at 54000 (checking) - 15000 (mortgage) - 6000 (card) = 33000: 2019's start.
    assert "Spending / net worth — 21.52%" in body  # 7100 / 33000
    # 2019 ends at 98000 - 10000 - 12100 = 75900: 10.7 years of 7100.
    assert "Net worth in years of spending 4.7 10.7" in body


def test_charts(tmp_path):
    body = page(tmp_path, query="?time=2019")
    [data] = re.findall(
        r'<svelte-component type="charts"><script type="application/json">(.*?)</script>', body
    )
    charts = {chart["label"]: chart for chart in json.loads(data)}
    net_worth = charts["Net worth"]
    assert net_worth["type"] == "bar"
    assert [(bar["date"], bar["balance"]) for bar in net_worth["data"]] == [
        ("2018-12-31", {"USD": "-47000"}),
        ("2019-12-31", {"USD": "-4100"}),
    ]
    bars = charts["Expenses by category"]["data"]
    assert bars[1]["account_balances"] == {
        "Expenses:Food": {"USD": "6100"},
        "Expenses:Housing": {"USD": "1000"},
    }


def test_expenses_by_category(tmp_path):
    body = text(page(tmp_path, query="?time=2019"))
    assert "Expenses:Food 6000 6100 85.9%" in body
    assert "Total 7000 7100" in body


def test_debt_paydown_in_the_last_year(tmp_path):
    body = page(tmp_path, query="?time=2019")
    section = text(body[body.index("<h3>Debt paydown in 2019</h3>") :])
    assert "Liabilities:Mortgage 95000 0 5000 90000" in section
    assert "Liabilities:CreditCard" not in section[: section.index("Paid down is principal")]


def test_classification_is_shown(tmp_path):
    body = text(page(tmp_path))
    assert "Assets:Bank:Checking cash name and type" in body
    assert "Assets:Brokerage investing declared" in body
    assert "Liabilities:CreditCard operating name and type" in body
    assert "Liabilities:Mortgage financing name and type" in body


def test_unknown_role_is_reported(tmp_path):
    body = text(page(tmp_path, LEDGER.replace('"investing"', '"invsting"')))
    assert "Assets:Brokerage: unknown cash-flow-role 'invsting', using the default" in body


def test_without_an_operating_currency(tmp_path):
    body = text(page(tmp_path, LEDGER.replace('option "operating_currency" "USD"\n', "")))
    assert "Set an operating_currency option" in body


def test_before_the_ledger_starts(tmp_path):
    body = text(page(tmp_path, query="?time=2015"))
    assert "No transactions up to 2015." in body
