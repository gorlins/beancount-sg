"""Tests for the Batch Edit Fava report (editing itself is tested in tests/test_batch_edit.py)."""

import pytest
from beancount.core.data import filter_txns
from fava.application import create_app
from fava.beans.funcs import hash_entry
from fava.core import FavaLedger

from beancount_sg.batch_edit import EditError
from beancount_sg.ext.batch_edit import FavaBackend

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
PREVIEW = URL + "preview"


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / "main.beancount"
    path.write_text(LEDGER)
    return path


@pytest.fixture
def client(ledger_path):
    return create_app([ledger_path], load=True).test_client()


def test_preview_lists_matches_with_links_to_each_transaction(client, ledger_path):
    response = client.get(PREVIEW, query_string=SEARCH)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "2 matching, 1 to change" in body
    for txn in list(filter_txns(FavaLedger(str(ledger_path)).all_entries))[:2]:
        assert f'<a href="#context-{hash_entry(txn)}">{txn.date}</a>' in body
    assert "Grocer" not in body
    assert 'id="batch-edit-apply" data-count="1"' in body


def test_preview_respects_the_fava_filter(client):
    body = client.get(PREVIEW, query_string={**SEARCH, "time": "2023"}).get_data(as_text=True)
    assert "0 matching, 0 to change" in body


def test_invalid_regex_is_reported(client):
    body = client.get(PREVIEW, query_string={"payee_regex": "("}).get_data(as_text=True)
    assert "Invalid regex" in body


def transactions(ledger_path):
    """(payee, category) of each transaction, freshly loaded from the file."""
    entries = FavaLedger(str(ledger_path)).all_entries
    return [(txn.payee, txn.postings[-1].account) for txn in filter_txns(entries)]


def test_apply_writes_the_previewed_edits_through_fava(client, ledger_path):
    response = client.post(
        URL + "apply",
        query_string={
            "payee_regex": "coffee",
            "new_payee": "Cafe",
            "new_category": "Expenses:Coffee",
        },
    )
    assert transactions(ledger_path) == [
        ("Cafe", "Expenses:Coffee"),
        ("Cafe", "Expenses:Coffee"),
        ("Grocer", "Expenses:Uncategorized"),
    ]
    # The result lists the edited transactions as they are now, linking to them.
    body = response.get_data(as_text=True)
    assert "Edited 2 transactions" in body
    edited = list(filter_txns(FavaLedger(str(ledger_path)).all_entries))[:2]
    for txn in edited:
        assert f'<a href="#context-{hash_entry(txn)}">{txn.date}</a>' in body
    assert body.count("<td>Cafe</td>") == 2
    assert body.count("<td>Expenses:Coffee</td>") == 2


def test_apply_respects_the_fava_filter(client, ledger_path):
    response = client.post(URL + "apply", query_string={**SEARCH, "time": "2023"})
    assert "Edited 0 transactions" in response.get_data(as_text=True)
    assert ledger_path.read_text() == LEDGER


def test_apply_reports_an_invalid_regex(client, ledger_path):
    response = client.post(URL + "apply", query_string={"payee_regex": "(", "new_payee": "X"})
    body = response.get_data(as_text=True)
    assert "Edited 0 transactions" in body
    assert "Invalid regex" in body
    assert ledger_path.read_text() == LEDGER


def test_preview_does_not_edit(client, ledger_path):
    client.get(PREVIEW, query_string=SEARCH)
    assert ledger_path.read_text() == LEDGER


def test_fava_backend_reads_and_writes_through_fava(ledger_path):
    ledger = FavaLedger(str(ledger_path))
    txn = next(filter_txns(ledger.all_entries))
    backend = FavaBackend(ledger)
    text = backend.read_entry(txn)
    assert text.startswith('2024-01-05 * "COFFEE SHOP #12" "Latte" #work')
    backend.write_entry(txn, text, text.replace("COFFEE SHOP #12", "Cafe"))
    assert transactions(ledger_path)[0][0] == "Cafe"


def test_fava_backend_reports_changed_text_as_an_edit_error(ledger_path):
    ledger = FavaLedger(str(ledger_path))
    txn = next(filter_txns(ledger.all_entries))
    with pytest.raises(EditError):
        FavaBackend(ledger).write_entry(txn, "not the current text", "new text")
    assert ledger_path.read_text() == LEDGER


SPLIT_LEDGER = """option "title" "Test"
2020-01-01 custom "fava-extension" "beancount_sg.ext.batch_edit"
2020-01-01 open Assets:Checking
2020-01-01 open Expenses:Coffee
2020-01-01 open Expenses:Food

2024-01-05 * "COFFEE SHOP #12" "Latte and a muffin"
  Assets:Checking  -9.00 USD
  Expenses:Coffee   5.00 USD
  Expenses:Food
"""


def test_split_shows_split_and_only_its_payee_changes(tmp_path):
    path = tmp_path / "main.beancount"
    path.write_text(SPLIT_LEDGER)
    client = create_app([path], load=True).test_client()
    search = {"payee_regex": "coffee", "new_payee": "Cafe", "new_category": "Expenses:Food"}

    body = client.get(PREVIEW, query_string=search).get_data(as_text=True)
    assert "<td>-SPLIT-</td>" in body

    body = client.post(URL + "apply", query_string=search).get_data(as_text=True)
    assert "Edited 1 transactions" in body
    assert path.read_text() == SPLIT_LEDGER.replace('"COFFEE SHOP #12"', '"Cafe"')


def test_page_explains_how_to_use_it(client):
    body = client.get(URL).get_data(as_text=True)
    assert "<summary>How to use</summary>" in body
    assert "-SPLIT-" in body


def test_page_is_just_the_form_and_an_empty_preview(client):
    # The page doesn't depend on its URL; the script loads the preview.
    body = client.get(URL, query_string={**SEARCH, "partial": "true"}).get_data(as_text=True)
    assert '<form id="batch-edit-form">' in body
    assert '<div id="batch-edit-preview"></div>' in body
    assert "coffee shop" not in body
