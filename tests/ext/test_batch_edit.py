import pytest
from beancount.core.data import filter_txns
from fava.application import create_app
from fava.beans.funcs import hash_entry
from fava.core import FavaLedger

LEDGER = """option "title" "Test"
2020-01-01 custom "fava-extension" "beancount_sg.ext.batch_edit"
2020-01-01 open Assets:Checking
2020-01-01 open Expenses:Uncategorized
2020-01-01 open Expenses:Coffee

2024-01-05 * "COFFEE SHOP #12" "Latte" #work
  plaid_payee: "Coffee Shop"
  Assets:Checking  -5.00 USD
  Expenses:Uncategorized ; from the bank

2024-01-06 * "Coffee Shop" "Espresso"
  Assets:Checking  -3.00 USD
  Expenses:Coffee

2024-01-07 * "Grocer" "Milk"
  Assets:Checking  -4.00 USD
  Expenses:Uncategorized
"""

# A search with a space in the regex, as typed into the form.
SEARCH = {
    "payee_regex": "coffee shop",
    "new_payee": "{plaid_payee}",
    "new_category": "Expenses:Coffee",
}
URL = "/test/extension/BatchEdit/"


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / "main.beancount"
    path.write_text(LEDGER)
    return path


@pytest.fixture
def client(ledger_path):
    return create_app([ledger_path], load=True).test_client()


def test_preview_lists_matches_with_links_to_each_transaction(client, ledger_path):
    response = client.get(URL, query_string=SEARCH)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    body = body[body.index("<h2>Batch Edit</h2>") : body.index("</sortable-table>")]
    assert "2 matching, 1 to change" in body
    for txn in list(filter_txns(FavaLedger(str(ledger_path)).all_entries))[:2]:
        assert f'<a href="#context-{hash_entry(txn)}">{txn.date}</a>' in body
    assert "Grocer" not in body
    assert 'id="batch-edit-apply" data-count="1"' in response.get_data(as_text=True)


def test_form_keeps_the_search_and_fava_filters(client):
    body = client.get(URL, query_string={**SEARCH, "time": "2024"}).get_data(as_text=True)
    assert '<input name="payee_regex" value="coffee shop">' in body
    assert '<input type="hidden" name="time" value="2024">' in body


def test_invalid_regex_is_reported(client):
    body = client.get(URL, query_string={"payee_regex": "("}).get_data(as_text=True)
    assert "Invalid regex" in body


def test_apply_edits_only_the_matching_lines(client, ledger_path):
    response = client.post(URL + "apply", query_string=SEARCH)
    assert response.get_json() == {"changed": 1, "errors": []}
    assert ledger_path.read_text() == LEDGER.replace(
        '"COFFEE SHOP #12" "Latte" #work', '"Coffee Shop" "Latte" #work'
    ).replace("Expenses:Uncategorized ; from the bank", "Expenses:Coffee ; from the bank")


def test_apply_respects_the_fava_filter(client, ledger_path):
    response = client.post(URL + "apply", query_string={**SEARCH, "time": "2023"})
    assert response.get_json() == {"changed": 0, "errors": []}
    assert ledger_path.read_text() == LEDGER


def test_preview_does_not_edit(client, ledger_path):
    client.get(URL, query_string=SEARCH)
    assert ledger_path.read_text() == LEDGER


def test_apply_several_edits_in_one_file(client, ledger_path):
    response = client.post(
        URL + "apply", query_string={"payee_regex": "coffee", "new_payee": "Cafe"}
    )
    assert response.get_json() == {"changed": 2, "errors": []}
    assert ledger_path.read_text() == LEDGER.replace(
        '"COFFEE SHOP #12" "Latte"', '"Cafe" "Latte"'
    ).replace('"Coffee Shop" "Espresso"', '"Cafe" "Espresso"')
