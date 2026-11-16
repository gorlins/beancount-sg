import json
import re

from fava.application import create_app

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
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def test_tables_show_spend_rewards_and_totals(tmp_path):
    body = text(page(tmp_path))
    assert "Groceries 3% 100.00 USD 3.00 USD 3.00 USD" in body
    assert "uncategorized 1.5% 20.00 USD 0.30 USD 0.30 USD" in body
    assert "Total 120.00 USD 3.30 USD 3.30 USD" in body
    assert "Dining 3x 50.00 USD 150.00 UR 1.50 USD" in body


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
    assert "No spending in the current filter." in body


def test_shows_configuration_errors(tmp_path):
    body = text(page(tmp_path, LEDGER.replace('rewards: "cashback"', 'rewards: "miles"')))
    assert "Liabilities:CreditCard:Cash: rewards must be" in body


def test_without_configured_cards(tmp_path):
    body = page(tmp_path, LEDGER.replace("rewards:", "note:"))
    assert "svelte-component" not in body
    assert "rewards:" in body  # the setup instructions
