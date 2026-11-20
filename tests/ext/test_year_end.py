import datetime
import html
import json
import re
from decimal import Decimal

import pytest
from fava.application import create_app

import beancount_sg.ext.year_end as year_end_ext
from beancount_sg.ext.year_end import change, changes
from beancount_sg.ext.year_end.metrics import YearSummary

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


def panel(body, title):
    """The text of the dashboard panel with this title."""
    start = body.index(f"<h3>{title}")
    return text(body[start : body.index("</section>", start)])


def cards(body):
    return text(body[body.index('<div class="ye-cards">') : body.index('<div class="ye-columns">')])


def year_headers(body):
    start = body.index("<h3>Net worth")
    head = body[body.index("<thead>", start) : body.index("</thead>", start)]
    return text("".join(re.findall(r'<th class="num">(.*?)</th>', head))).split()


def test_defaults_to_five_years_ending_this_year(tmp_path):
    body = page(tmp_path)
    assert year_headers(body) == ["2021", "2022", "2023", "2024", "2025", "YTD"]
    assert "2025 is year-to-date, through 2025-07-01" in text(body)


def test_a_single_year_filter_shows_up_to_five_years_ending_with_it(tmp_path):
    assert year_headers(page(tmp_path, query="?time=2019")) == ["2018", "2019"]
    assert year_headers(page(tmp_path, query="?time=2023-06")) == [
        "2019",
        "2020",
        "2021",
        "2022",
        "2023",
    ]


def test_a_range_filter_shows_its_years(tmp_path):
    assert year_headers(page(tmp_path, query="?time=2020+-+2022")) == ["2020", "2021", "2022"]
    # At most five: the latest.
    assert year_headers(page(tmp_path, query="?time=2018+-+2024")) == [
        "2020",
        "2021",
        "2022",
        "2023",
        "2024",
    ]


def test_account_and_advanced_filters_apply(tmp_path):
    body = page(tmp_path, query="?time=2019&filter=-Groceries")
    assert "Expenses 1,000 1,000 ■ no change" in panel(body, "Income &amp; savings")
    # Balances still include everything before the years shown.
    assert "Cash 54,000 98,000" in panel(body, "Net worth")


def test_years_start_with_the_first_income_or_expenses(tmp_path):
    # Opening balances alone don't make a year.
    ledger = LEDGER.replace('2018-01-01 * "Opening balances"', '2017-12-31 * "Opening balances"')
    ledger = ledger.replace("2018-01-01 open", "2017-01-01 open")
    assert year_headers(page(tmp_path, ledger, query="?time=2019")) == ["2018", "2019"]


def test_cards_show_the_last_year_and_its_change(tmp_path):
    found = cards(page(tmp_path, query="?time=2019"))
    # 2019 ends at checking 98000 - mortgage 90000 - card 12100.
    assert (
        "Net worth -4,100 ▲ +42,900 (+91.3%) vs 2018 assets minus liabilities, at the year's end"
        in found
    )
    assert (
        "Investable assets 98,000 ▲ +44,000 (+81.5%) vs 2018"
        " cash and investments, at the year's end" in found
    )
    assert "Income 50,000 ■ no change vs 2018 in 2019" in found
    assert "Expenses 7,100 ▲ +100 (+1.4%) vs 2018 in 2019" in found
    assert "Savings rate 85.8% ▼ −0.2 pts vs 2018 42,900 saved in 2019" in found
    # The mortgage fell 5000, but the unpaid card grew 6100.
    assert "Debt paid down -1,100 ▲ +99,900 (+98.9%) vs 2018 in 2019; 102,100 still owed" in found
    # 2019's spending, 7100, against its ending cash and investments, 98000.
    assert (
        "Withdrawal rate 7.24% ▼ −5.7 pts vs 2018 12 months' spending ÷ investable assets"
        " at the year's end" in found
    )
    assert "Emergency fund 165.6 mo ▲ +73.1 vs 2018 98,000 cash at the year's end" in found


def tone(body, label):
    """The CSS class of the change shown with this label (on a card and in a table)."""
    [found] = set(re.findall(rf'class="ye-delta ye-(\w+)">[^<]*{re.escape(label)}', body))
    return found


def test_changes_are_green_when_good_and_red_when_bad(tmp_path):
    body = page(tmp_path, query="?time=2019")
    assert tone(body, "+42,900 (+91.3%)") == "good"  # net worth up
    assert tone(body, "−1,100 (−1.1%)") == "bad"  # debt up
    assert tone(body, "+100 (+1.4%) vs 2018") == "bad"  # expenses up
    assert tone(body, "−0.2 pts vs 2018") == "bad"  # savings rate down
    assert tone(body, "no change vs 2018") == "flat"


def test_net_worth_and_income_panels(tmp_path):
    body = page(tmp_path, query="?time=2019")
    net_worth = panel(body, "Net worth")
    assert "Cash 54,000 98,000 ▲ +44,000 (+81.5%)" in net_worth
    assert "Property 0 0 ■ no change" in net_worth
    assert "Debt -101,000 -102,100 ▼ −1,100 (−1.1%)" in net_worth  # the mortgage and card
    assert "Other 0 0 ■ no change" in net_worth
    assert "Net worth -47,000 -4,100 ▲ +42,900 (+91.3%)" in net_worth
    assert "Investable assets 54,000 98,000" in net_worth
    income = panel(body, "Income &amp; savings")
    assert "Income 50,000 50,000 ■ no change" in income
    assert "Savings 43,000 42,900 ▼ −100 (−0.2%)" in income
    assert "Savings rate 86.0% 85.8% ▼ −0.2 pts" in income
    # 2018 opened the mortgage: 100000 owed, less 5000 paid and the card's 6000.
    assert "Debt paid down -101,000 -1,100 ▲ +99,900 (+98.9%)" in income
    assert "12 months' spending, against balances at the year's end" in income
    # Each year's spending against its ending cash and investments: 54000, then 98000.
    assert "Withdrawal rate 13.0% 7.2% ▼ −5.7 pts" in income
    # Without a positive net worth, spending / net worth isn't meaningful.
    assert "Spending / net worth — —" in income
    assert "Emergency fund (months) 92.6 165.6 ▲ +73.1" in income


def test_a_year_to_dates_flows_are_not_compared(tmp_path):
    body = page(tmp_path)
    found = cards(body)
    assert "Income 50,000 year to date" in found
    assert "Expenses 7,700 year to date" in found
    # Its spending ratios use the last 12 months, so they are.
    assert "Withdrawal rate 2.13% ▼ −0.3 pts vs 2024" in found
    assert "its spending ratios use the last 12 months" in text(body)


def test_spending_ratios_with_a_positive_net_worth(tmp_path):
    ledger = LEDGER.replace("Liabilities:Mortgage  -100000 USD", "Liabilities:Mortgage  -20000 USD")
    income = panel(page(tmp_path, ledger, query="?time=2019"), "Income &amp; savings")
    # 2018 ends at 54000 (checking) - 15000 (mortgage) - 6000 (card) = 33000, and 2019 at
    # 98000 - 10000 - 12100 = 75900.
    assert "Spending / net worth 21.2% 9.4%" in income  # 7000 / 33000, 7100 / 75900


def test_charts(tmp_path):
    body = page(tmp_path, query="?time=2019")
    found = re.findall(
        r'<svelte-component type="charts"><script type="application/json">(.*?)</script>', body
    )
    # The net worth charts share a component, so Fava switches between them.
    assert [chart["label"] for chart in json.loads(found[0])] == [
        "Net worth",
        "Assets & liabilities",
    ]
    charts = {chart["label"]: chart for data in found for chart in json.loads(data)}
    net_worth = charts["Net worth"]
    assert [
        (bar["date"], bar["balance"], bar["account_balances"]) for bar in net_worth["data"]
    ] == [
        ("2018-12-31", {"USD": "-47000"}, {}),
        ("2019-12-31", {"USD": "-4100"}, {}),
    ]
    stacked = charts["Assets & liabilities"]
    assert [(bar["date"], bar["balance"], bar["account_balances"]) for bar in stacked["data"]] == [
        (
            "2018-12-31",
            {"USD": "-47000"},
            {"Assets": {"USD": "54000"}, "Liabilities": {"USD": "-101000"}},
        ),
        (
            "2019-12-31",
            {"USD": "-4100"},
            {"Assets": {"USD": "98000"}, "Liabilities": {"USD": "-102100"}},
        ),
    ]
    bars = charts["Expenses by category"]["data"]
    assert bars[1]["account_balances"] == {
        "Expenses:Food": {"USD": "6100"},
        "Expenses:Housing": {"USD": "1000"},
    }


def test_expenses_by_category(tmp_path):
    found = panel(page(tmp_path, query="?time=2019"), "Expenses by category")
    assert "Expenses:Food 6,000 6,100 ▲ +100 (+1.7%)" in found
    assert "Expenses:Housing 1,000 1,000 ■ no change" in found
    assert "Total 7,000 7,100 ▲ +100 (+1.4%)" in found


def test_debt_in_the_last_year(tmp_path):
    found = panel(page(tmp_path, query="?time=2019"), "Debt in 2019")
    # Start, end, and paid down: negative for the card, whose balance grew.
    assert "Liabilities:CreditCard 6,000 12,100 -6,100" in found
    assert "Liabilities:Mortgage 95,000 90,000 5,000" in found
    assert "Total 101,000 102,100 -1,100" in found


def test_classification_is_shown(tmp_path):
    body = text(page(tmp_path))
    assert "Assets:Bank:Checking cash cash, by default" in body
    assert "Assets:Brokerage investments investing, declared on Assets:Brokerage" in body
    assert "Liabilities:CreditCard debt financing, by default" in body
    assert "Liabilities:Mortgage debt financing, by default" in body


def test_unknown_role_is_reported(tmp_path):
    body = text(page(tmp_path, LEDGER.replace('"investing"', '"invsting"')))
    assert (
        "Assets:Brokerage: cash-flow-role 'invsting' isn't one of"
        " cash, operating, investing, financing; it's ignored" in body
    )


def test_without_an_operating_currency(tmp_path):
    body = text(page(tmp_path, LEDGER.replace('option "operating_currency" "USD"\n', "")))
    assert "Set an operating_currency option" in body


def test_before_the_ledger_starts(tmp_path):
    body = text(page(tmp_path, query="?time=2015"))
    assert "No transactions up to 2015." in body


@pytest.mark.parametrize(
    ("current", "previous", "higher_is_better", "tone", "label"),
    [
        (Decimal(110), Decimal(100), True, "good", "+10 (+10.0%)"),
        (Decimal(90), Decimal(100), True, "bad", "−10 (−10.0%)"),
        (Decimal(90), Decimal(100), False, "good", "−10 (−10.0%)"),
        (Decimal(1500), Decimal(0), True, "good", "+1,500"),  # no percentage of zero
        (Decimal(100), Decimal(100), True, "flat", "no change"),
    ],
)
def test_change(current, previous, higher_is_better, tone, label):
    found = change(current, previous, higher_is_better=higher_is_better)
    assert (found.tone, found.label()) == (tone, label)


def test_change_labels_and_unknowns():
    assert change(Decimal("45.5"), Decimal("40"), higher_is_better=True).label("points") == (
        "+5.5 pts"
    )
    assert change(Decimal("6.1"), Decimal("5.4")).label("number") == "+0.7"
    assert change(None, Decimal(1)) is None


def test_changes_skip_a_year_to_dates_flows():
    complete = YearSummary(2024, datetime.date(2025, 1, 1))
    partial = YearSummary(2025, datetime.date(2025, 7, 2))
    values = [Decimal(100), Decimal(50)]
    assert changes(values, [complete, partial], flow=True) == [None, None]
    assert changes(values, [complete, partial])[1].label() == "−50 (−50.0%)"


def test_investment_returns_have_their_own_row(tmp_path):
    ledger = (
        LEDGER
        + """
2018-01-01 open Assets:Retirement
2018-01-01 open Income:CapitalGains USD
  cash-flow-role: "investing"
2019-06-01 * "Sold and bought again"
  Assets:Retirement  3000 USD
  Income:CapitalGains
"""
    )
    body = page(tmp_path, ledger, query="?time=2019")
    income = panel(body, "Income &amp; savings")
    # Income and savings are unchanged; the gain is on its own row.
    assert "Income 50,000 50,000 ■ no change" in income
    assert "Savings 43,000 42,900" in income
    assert "Investment returns 0 3,000" in income
    assert "Income:CapitalGains investment returns investing, declared on Income:CapitalGains" in (
        text(body)
    )


def test_no_investment_returns_row_without_any(tmp_path):
    assert "Investment returns" not in panel(
        page(tmp_path, query="?time=2019"), "Income &amp; savings"
    )
