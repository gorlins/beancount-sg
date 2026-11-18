import html
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from beancount import loader
from beancount.core.data import filter_txns
from fava.application import create_app
from fava.core.filter_parser import parse_filter

LEDGER = """
option "title" "Test"
2020-01-01 custom "fava-extension" "beancount_sg.ext.rewards"

2020-01-01 open Assets:Checking
2020-01-01 open Liabilities:CreditCard:Cash USD
  rewards: "cashback"
  rewards-rate: 1.5
  rewards-rate-groceries: 3
2020-01-01 open Liabilities:CreditCard:Sapphire USD
  rewards: "points"
  rewards-rate-dining: 3
  rewards-unit: "UR"
  rewards-point-value: 0.01
2020-01-01 open Expenses:Food
2020-01-01 open Expenses:Shopping

2024-03-01 * "Market"
  category: "Groceries"
  Liabilities:CreditCard:Cash  -100.00 USD
  Expenses:Food

2024-03-02 * "Store"
  Liabilities:CreditCard:Cash  -20.00 USD
  Expenses:Shopping

2025-03-03 * "Bistro"
  category: "Dining"
  Liabilities:CreditCard:Sapphire  -50.00 USD
  Expenses:Food
"""


def page(tmp_path, text=LEDGER, query=""):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(text)
    client = create_app([ledger], load=True).test_client()
    response = client.get(f"/test/extension/CreditCardRewards/{query}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def charts(body):
    match = re.search(
        r'<svelte-component type="charts"><script type="application/json">(.*?)</script>',
        body,
        re.DOTALL,
    )
    return {chart["label"]: chart["data"] for chart in json.loads(match.group(1))}


def leaves(node):
    if not node["children"]:
        return {node["account"]: node["balance"]}
    return {k: v for child in node["children"] for k, v in leaves(child).items()}


def text(body):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


def test_table_shows_each_card_and_category_with_totals(tmp_path):
    body = text(page(tmp_path))
    assert "Liabilities:CreditCard:Cash Groceries 3% 100.00 USD 3.00 USD 3.00 USD" in body
    assert "Liabilities:CreditCard:Cash uncategorized 1.5% 20.00 USD 0.30 USD 0.30 USD" in body
    assert "Liabilities:CreditCard:Sapphire Dining 3x 50.00 USD 150.00 UR 1.50 USD" in body
    assert "Total 170.00 USD 3.30 USD 150.00 UR 4.80 USD" in body


def test_setup_instructions_follow_the_report(tmp_path):
    body = page(tmp_path)
    assert body.index("<table") < body.index("How to set up")


def category_link(body, category):
    """The path and query parameters of the table's link for a category."""
    [href] = re.findall(rf'<a href="([^"]+)">{category}</a>', body)
    url = urlsplit(html.unescape(href))
    return unquote(url.path), {key: value for key, [value] in parse_qs(url.query).items()}


def matching(ledger_text, fava_filter):
    """The narrations of the ledger's transactions that a Fava filter matches."""
    entries, _, _ = loader.load_string(ledger_text)
    expression = parse_filter(fava_filter)
    return sorted(txn.narration for txn in filter_txns(entries) if expression(txn))


CATEGORIES = (
    LEDGER
    + """
2024-03-05 * "Deli"
  Liabilities:CreditCard:Cash  -30.00 USD
  Expenses:Food  20.00 USD
    category: "Groceries"
  Expenses:Shopping  10.00 USD
"""
)


def test_categories_link_to_the_card_filtered_by_category(tmp_path):
    body = page(tmp_path, CATEGORIES, query="?time=2024")
    path, params = category_link(body, "Groceries")
    assert path == "/test/account/Liabilities:CreditCard:Cash/"
    assert params["time"] == "2024"
    assert matching(CATEGORIES, params["filter"]) == ["Deli", "Market"]
    _, params = category_link(body, "uncategorized")
    assert matching(CATEGORIES, params["filter"]) == ["Deli", "Store"]


ENABLE = 'custom "fava-extension" "beancount_sg.ext.rewards"'


def with_config(ledger, config):
    """The ledger with the extension enabled with a config string."""
    return ledger.replace(ENABLE, f'{ENABLE} "{config}"')


PAYMENTS = with_config(
    CATEGORIES,
    "{\n  'exclude_accounts': ['Expenses:CardPayments'],\n}",
) + (
    """
2020-01-01 open Expenses:CardPayments

2024-03-10 * "Autopay"
  Liabilities:CreditCard:Cash  70.00 USD
  Expenses:CardPayments

2024-03-11 * "Autopay with category"
  category: "Groceries"
  Liabilities:CreditCard:Cash  30.00 USD
  Expenses:CardPayments
"""
)


def test_excluded_payments_are_neither_counted_nor_linked(tmp_path):
    body = page(tmp_path, PAYMENTS)
    table = text(body)
    assert "Liabilities:CreditCard:Cash Groceries 3% 120.00 USD" in table
    assert "Liabilities:CreditCard:Cash uncategorized 1.5% 30.00 USD" in table
    _, params = category_link(body, "Groceries")
    assert matching(PAYMENTS, params["filter"]) == ["Deli", "Market"]
    _, params = category_link(body, "uncategorized")
    assert matching(PAYMENTS, params["filter"]) == ["Deli", "Store"]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ("['Expenses:CardPayments']", "the extension's config must be like"),
        ("{'exclude': ['Expenses:CardPayments']}", "the extension's config must be like"),
        ("{'exclude_accounts': 'Expenses:CardPayments'}", "exclude_accounts must be a list"),
        ("{'exclude_accounts': ['card payments']}", "exclude_accounts must be a list"),
    ],
)
def test_invalid_config_is_reported_and_excludes_nothing(tmp_path, config, message):
    body = text(page(tmp_path, with_config(PAYMENTS, config)))
    assert f"Credit Card Rewards: {message}" in body
    assert "Liabilities:CreditCard:Cash uncategorized 1.5% -40.00 USD" in body


def test_category_links_keep_the_current_filter(tmp_path):
    body = page(tmp_path, CATEGORIES, query="?filter=Deli")
    _, params = category_link(body, "Groceries")
    assert matching(CATEGORIES, params["filter"]) == ["Deli"]


def test_category_links_escape_the_category(tmp_path):
    ledger = LEDGER.replace('"Groceries"', '"Food (and) \\"Drink\\""')
    body = page(tmp_path, ledger)
    [href] = re.findall(r'<a href="([^"]+)">Food \(and\) &#34;Drink&#34;</a>', body)
    fava_filter = parse_qs(urlsplit(html.unescape(href)).query)["filter"][0]
    assert matching(ledger, fava_filter) == ["Market"]


def test_chart_category_nodes_have_links(tmp_path):
    body = page(tmp_path)
    [links] = re.findall(
        r'<script type="application/json" id="rewards-category-links">(.*?)</script>', body
    )
    links = json.loads(links)
    assert set(links) == {
        "Liabilities:CreditCard:Cash:Groceries",
        "Liabilities:CreditCard:Cash:uncategorized",
        "Liabilities:CreditCard:Sapphire:Dining",
    }
    assert (
        html.unescape(category_link(body, "Dining")[0])
        in links["Liabilities:CreditCard:Sapphire:Dining"]
    )


def test_charts_show_spend_and_value_by_card_and_category(tmp_path):
    found = charts(page(tmp_path))
    assert set(found) == {"Spend", "Value"}
    assert found["Spend"]["account"] == "Liabilities:CreditCard"
    assert leaves(found["Spend"]) == {
        "Liabilities:CreditCard:Cash:Groceries": {"USD": "100.00"},
        "Liabilities:CreditCard:Cash:uncategorized": {"USD": "20.00"},
        "Liabilities:CreditCard:Sapphire:Dining": {"USD": "50.00"},
    }
    assert leaves(found["Value"])["Liabilities:CreditCard:Sapphire:Dining"] == {"USD": "1.5000"}
    assert found["Value"]["balance_children"] == {"USD": "4.8000"}


def test_points_without_a_value_are_left_out_of_the_value_chart(tmp_path):
    found = charts(page(tmp_path, LEDGER.replace("  rewards-point-value: 0.01\n", "")))
    assert "Liabilities:CreditCard:Sapphire:Dining" not in leaves(found["Value"])
    assert "Liabilities:CreditCard:Sapphire:Dining" in leaves(found["Spend"])


def test_a_single_card_is_a_node_under_its_parent(tmp_path):
    single = LEDGER.replace('  rewards: "points"\n', "")
    spend = charts(page(tmp_path, single))["Spend"]
    assert spend["account"] == "Liabilities:CreditCard"
    assert [child["account"] for child in spend["children"]] == ["Liabilities:CreditCard:Cash"]


def test_respects_the_time_filter(tmp_path):
    body = text(page(tmp_path, query="?time=2025"))
    assert "Dining" in body
    assert "Groceries" not in body
    assert "No spending in the current filter." in text(page(tmp_path, query="?time=2023"))


def test_shows_configuration_errors(tmp_path):
    body = text(page(tmp_path, LEDGER.replace('rewards: "cashback"', 'rewards: "miles"')))
    assert "Liabilities:CreditCard:Cash: rewards must be" in body


def test_without_configured_cards(tmp_path):
    body = page(tmp_path, LEDGER.replace("rewards:", "note:"))
    assert "svelte-component" not in body
    assert "rewards:" in body  # the setup instructions
