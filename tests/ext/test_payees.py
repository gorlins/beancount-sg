import html
import re
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from beancount import loader
from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES
from beancount.core.data import filter_txns
from fava.application import create_app
from fava.core.filter_parser import parse_filter

from beancount_sg.batch_edit import find_transactions
from beancount_sg.builders import A
from beancount_sg.ext.payees import (
    mixed_categories,
    payee_filter,
    payee_pattern,
    payees,
    similar_names,
)

ENABLE = 'custom "fava-extension" "beancount_sg.ext.payees"'

LEDGER = f"""
option "title" "Test"
2020-01-01 {ENABLE}

2020-01-01 open Assets:Checking
2020-01-01 open Expenses:Groceries
2020-01-01 open Expenses:Dining
2020-01-01 open Expenses:Home
2020-01-01 open Income:Refunds
"""


def txn(date, payee, *postings, narration="Purchase"):
    payee_text = f'"{payee}" ' if payee else ""
    lines = "".join(f"\n  {account}  {amount} USD" for account, amount in postings)
    return f'\n{date} * {payee_text}"{narration}"{lines}\n  Assets:Checking\n'


TRANSACTIONS = "".join(
    [
        *(
            txn(f"2025-01-{day:02}", "FreshMart", ("Expenses:Groceries", "50.00"))
            for day in (1, 2, 3)
        ),
        txn("2025-01-04", "FreshMart", ("Expenses:Dining", "12.00")),  # likely a mistake
        txn("2025-01-05", "BigBox", ("Expenses:Groceries", "30.00")),
        txn("2025-01-06", "BigBox", ("Expenses:Home", "40.00")),
        # A split, in two categories.
        txn("2025-01-07", "BigBox", ("Expenses:Groceries", "10.00"), ("Expenses:Home", "5.00")),
        txn("2025-01-08", "BigBox", ("Income:Refunds", "-8.00")),
        txn("2025-01-09", "Corner Coffee", ("Expenses:Dining", "4.00")),
        txn("2025-01-10", "SQ *CORNER COFFEE 0412", ("Expenses:Dining", "4.50")),
        txn("2025-01-11", "SQ *CORNER COFFEE 0412", ("Expenses:Dining", "5.00")),
        txn("2025-01-12", "", ("Expenses:Home", "1.00")),  # no payee
        txn("2025-01-12", "", ("Expenses:Dining", "1.00")),  # no payee
    ]
)


def load(text=LEDGER + TRANSACTIONS):
    entries, errors, _ = loader.load_string(text)
    assert not errors
    return entries


def test_payee_categories():
    found = payees(load(), DEFAULT_ACCOUNT_TYPES)
    assert set(found) == {"FreshMart", "BigBox", "Corner Coffee", "SQ *CORNER COFFEE 0412"}
    bigbox = found["BigBox"]
    assert bigbox.transactions == 4
    # The split counts in both of its categories.
    assert {account: usage.transactions for account, usage in bigbox.categories.items()} == {
        "Expenses:Groceries": 2,
        "Expenses:Home": 2,
        "Income:Refunds": 1,
    }
    assert bigbox.categories["Expenses:Groceries"].total == [A("40.00", "USD")]
    assert bigbox.categories["Income:Refunds"].total == [A("-8.00", "USD")]


def test_main_category_and_share():
    found = payees(load(), DEFAULT_ACCOUNT_TYPES)
    freshmart = found["FreshMart"]
    assert freshmart.main.account == "Expenses:Groceries"
    assert [usage.account for usage in freshmart.others] == ["Expenses:Dining"]
    assert freshmart.main_share == Decimal(75)
    # A tie goes to the first account by name.
    assert found["BigBox"].main.account == "Expenses:Groceries"


def test_payees_always_split_the_same_way_are_not_mixed():
    ledger = LEDGER + "".join(
        txn(f"2025-01-0{day}", "Handy", ("Expenses:Home", "5.00"), ("Expenses:Groceries", "1.00"))
        for day in (1, 2)
    )
    handy = payees(load(ledger), DEFAULT_ACCOUNT_TYPES)["Handy"]
    assert len(handy.categories) == 2
    assert not handy.mixed
    assert mixed_categories({"Handy": handy}) == []


def test_mixed_categories_mostly_in_one_first():
    found = payees(load(), DEFAULT_ACCOUNT_TYPES)
    assert [payee.name for payee in mixed_categories(found)] == ["FreshMart", "BigBox"]


def test_similar_names_are_grouped():
    counts = {"Corner Coffee": 1, "SQ *CORNER COFFEE 0412": 2, "FreshMart": 4, "BigBox": 4}
    assert similar_names(counts) == [["SQ *CORNER COFFEE 0412", "Corner Coffee"]]


def test_groups_are_centred_on_the_most_common_name():
    counts = {"Whole Foods Market #102": 3, "Whole Foods": 5, "WHOLE FOODS MARKET #103": 1}
    assert similar_names(counts) == [
        ["Whole Foods", "Whole Foods Market #102", "WHOLE FOODS MARKET #103"]
    ]


def test_similar_names_are_not_chained():
    # "Delta Air Lines" is similar to both others, which aren't similar to each
    # other. "Air Lines" only joins when "Delta Air Lines" starts the group.
    counts = {"Delta": 3, "Delta Air Lines": 2, "Air Lines": 1}
    assert similar_names(counts) == [["Delta", "Delta Air Lines"]]
    counts = {"Delta": 1, "Delta Air Lines": 3, "Air Lines": 2}
    assert similar_names(counts) == [["Delta Air Lines", "Air Lines", "Delta"]]


def test_names_without_a_shared_word_are_not_compared():
    assert similar_names({"Whole Foods": 2, "WholeFoods": 1}) == []


def test_similarity_threshold():
    assert similar_names({"Target Store": 2, "Target Stores Inc": 1}, similarity=100) == []
    assert similar_names({"Target Store": 2, "Target Stores Inc": 1}, similarity=80) == [
        ["Target Store", "Target Stores Inc"]
    ]


@pytest.mark.parametrize(
    "name", ["FreshMart", 'Joe\'s "Best" Diner (No. 1)', "A+B*C?", "Corner Coffee"]
)
def test_payee_filter_and_pattern_match_exactly(name):
    entries = load(
        LEDGER
        + txn("2025-01-01", name.replace('"', '\\"'), ("Expenses:Dining", "1.00"))
        + txn("2025-01-02", name.replace('"', '\\"') + " Two", ("Expenses:Dining", "1.00"))
    )
    expression = parse_filter(payee_filter([name]))
    assert [t.payee for t in filter_txns(entries) if expression(t)] == [name]
    assert re.match(payee_pattern([name]), name.upper(), re.IGNORECASE)
    assert not re.match(payee_pattern([name]), name + " Two", re.IGNORECASE)


def page(tmp_path, text=LEDGER + TRANSACTIONS, query=""):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(text)
    client = create_app([ledger], load=True).test_client()
    response = client.get(f"/test/extension/PayeeReview/{query}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(body):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


def section(body, title):
    start = body.index(f"<h3>{title}</h3>")
    end = body.find("<h3>", start + 1)
    return body[start : end if end > 0 else body.index("<details>")]


def links(body, label):
    """The targets of the links with this text: their path and query parameters."""
    found = []
    for href in re.findall(rf'<a href="([^"]+)"[^>]*>{re.escape(label)}</a>', body):
        url = urlsplit(html.unescape(href))
        found.append((unquote(url.path), {k: v for k, [v] in parse_qs(url.query).items()}))
    return found


def matching_payees(fava_filter):
    expression = parse_filter(fava_filter)
    return sorted({t.payee for t in filter_txns(load()) if expression(t)})


def test_summary_and_tables(tmp_path):
    body = page(tmp_path)
    assert "4 payees in the current filter: 2 in more than one category, and 1 group" in text(body)
    mixed = text(section(body, "Payees in more than one category"))
    assert (
        "FreshMart 4 75% Expenses:Groceries : 3 × 150.00 USD Expenses:Dining : 1 × 12.00 USD"
        in (mixed)
    )
    assert mixed.index("FreshMart") < mixed.index("BigBox")
    similar = text(section(body, "Similar payee names"))
    assert "SQ *CORNER COFFEE 0412 3 SQ *CORNER COFFEE 0412 (2) Corner Coffee (1)" in similar


def test_payee_and_category_links_filter_by_payee(tmp_path):
    body = page(tmp_path, query="?time=2025")
    [(path, params)] = links(section(body, "Payees in more than one category"), "FreshMart")
    assert path == "/test/income_statement/"
    assert params["time"] == "2025"
    assert matching_payees(params["filter"]) == ["FreshMart"]
    [(path, params)] = links(body, "Expenses:Dining")[:1]
    assert path == "/test/account/Expenses:Dining/"
    assert matching_payees(params["filter"]) == ["FreshMart"]
    similar = section(body, "Similar payee names")
    [(path, params)] = links(similar, "SQ *CORNER COFFEE 0412")[:1]
    assert matching_payees(params["filter"]) == ["Corner Coffee", "SQ *CORNER COFFEE 0412"]


def test_links_keep_the_current_filter(tmp_path):
    body = page(tmp_path, query="?filter=Purchase")
    [(_, params)] = links(section(body, "Payees in more than one category"), "FreshMart")
    assert params["filter"].startswith("(Purchase) ")
    assert matching_payees(params["filter"]) == ["FreshMart"]


def test_no_batch_edit_links_without_batch_edit(tmp_path):
    body = page(tmp_path)
    assert "Recategorize</a>" not in body
    assert "Rename</a>" not in body


def test_batch_edit_links_fill_in_the_fix(tmp_path):
    ledger = LEDGER.replace(
        ENABLE, f'{ENABLE}\n2020-01-01 custom "fava-extension" "beancount_sg.ext.batch_edit"'
    )
    body = page(tmp_path, ledger + TRANSACTIONS)
    # From the file, since Batch Edit only finds transactions it can edit.
    entries, _, _ = loader.load_file(str(tmp_path / "main.beancount"))
    [(path, params)] = links(body, "Recategorize")[:1]  # FreshMart
    assert path == "/test/extension/BatchEdit/"
    assert params["new_category"] == "Expenses:Groceries"
    assert {t.payee for t in find_transactions(entries, params["payee_regex"])} == {"FreshMart"}
    [(path, params)] = links(body, "Rename")
    assert params["new_payee"] == "SQ *CORNER COFFEE 0412"
    found = find_transactions(entries, params["payee_regex"])
    assert {t.payee for t in found} == {"Corner Coffee", "SQ *CORNER COFFEE 0412"}


def test_respects_the_time_filter(tmp_path):
    body = text(page(tmp_path, query="?time=2024"))
    assert "0 payees in the current filter" in body
    assert "None: every payee is in a single category." in body
    assert "None found." in body
