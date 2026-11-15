import re

import pytest
from beancount import loader
from beancount.core.data import filter_txns
from fava.core.file import get_entry_slice

from beancount_sg.batch_edit import (
    automatic_posting,
    edit_source,
    find_transactions,
    new_payee,
    plan_edits,
)
from beancount_sg.builders import A, P, T

LEDGER = """
2024-01-05 * "Coffee Shop" "Latte"
  Assets:Checking  -5.00 USD
  Expenses:Uncategorized

2024-01-06 * "COFFEE SHOP #12" "Espresso"
  Assets:Checking  -3.00 USD
  Expenses:Uncategorized

2024-01-07 * "Grocer" "Weekly coffee and milk"
  Assets:Checking  -40.00 USD
  Expenses:Uncategorized
"""


@pytest.fixture
def load_file(tmp_path):
    """Load a ledger from a real file, as Fava does, so entries can be edited."""

    def load_file(ledger: str):
        path = tmp_path / "main.beancount"
        path.write_text('plugin "beancount.plugins.auto_accounts"\n' + ledger)
        entries, errors, _ = loader.load_file(str(path))
        assert errors == []
        return entries

    return load_file


def payees(found):
    return [txn.payee for txn in found]


def test_find_by_payee_is_case_insensitive_and_anchored_at_the_start(load_file):
    entries = load_file(LEDGER)
    assert payees(find_transactions(entries, payee_regex="coffee shop")) == [
        "Coffee Shop",
        "COFFEE SHOP #12",
    ]
    assert payees(find_transactions(entries, payee_regex="shop")) == []
    assert payees(find_transactions(entries, payee_regex=".*shop")) == [
        "Coffee Shop",
        "COFFEE SHOP #12",
    ]


def test_find_by_narration_and_both(load_file):
    entries = load_file(LEDGER)
    assert payees(find_transactions(entries, narration_regex=".*coffee")) == ["Grocer"]
    assert payees(find_transactions(entries, payee_regex="coffee", narration_regex="esp")) == [
        "COFFEE SHOP #12"
    ]


def test_find_needs_a_pattern(load_file):
    entries = load_file(LEDGER)
    assert find_transactions(entries) == []


def test_find_skips_generated_transactions(load_file):
    written = next(filter_txns(load_file(LEDGER)))
    generated = T("2024-01-05", payee="Coffee Shop", meta={"filename": "<pad>", "lineno": 0})
    built = T("2024-01-05", payee="Coffee Shop")
    assert find_transactions([written, generated, built], payee_regex="coffee") == [written]


def test_find_rejects_invalid_patterns():
    with pytest.raises(re.error):
        find_transactions([], payee_regex="(")


def test_automatic_posting(load_file):
    entries = load_file(LEDGER)
    txn = next(filter_txns(entries))
    assert automatic_posting(txn).account == "Expenses:Uncategorized"
    assert automatic_posting(T("2024-01-05", postings=[P("Assets:A", A(1, "USD"))])) is None


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("Starbucks", "Starbucks"),
        ("{plaid_payee}", "Starbucks Corp"),
        ("{plaid_payee} ({store})", "Starbucks Corp (12)"),
        ("{missing}", None),
        ("", None),
        ("{{literal}}", "{literal}"),
    ],
)
def test_new_payee(template, expected):
    txn = T("2024-01-05", meta={"plaid_payee": "Starbucks Corp", "store": 12})
    assert new_payee(txn, template) == expected


@pytest.fixture
def source_and_txn(load_file):
    """The first transaction's source lines, as Fava reads them, and the transaction."""

    def source_and_txn(ledger: str):
        txn = next(filter_txns(load_file(ledger)))
        return get_entry_slice(txn).slice, txn

    return source_and_txn


OPENS = """
2020-01-01 open Assets:Checking
2020-01-01 open Expenses:Uncategorized
2020-01-01 open Expenses:Coffee
"""


@pytest.mark.parametrize(
    ("header", "payee", "expected"),
    [
        ('2024-01-05 * "Old" "Latte"', "New", '2024-01-05 * "New" "Latte"'),
        ('2024-01-05 * "Latte"', "New", '2024-01-05 * "New" "Latte"'),  # payee inserted
        (
            '2024-01-05 ! "Old"   "Latte"  #tag ^link ; note',
            "New",
            '2024-01-05 ! "New"   "Latte"  #tag ^link ; note',
        ),
        ('2024-01-05 txn "Old \\"Q\\"" "Latte"', "New", '2024-01-05 txn "New" "Latte"'),
        (
            '2024-01-05 * "Old" "Latte"',
            'Say "hi" \\o/',
            '2024-01-05 * "Say \\"hi\\" \\\\o/" "Latte"',
        ),
    ],
)
def test_edit_source_sets_payee_and_keeps_the_rest(
    source_and_txn, load_file, header, payee, expected
):
    source, txn = source_and_txn(
        OPENS + f"\n{header}\n  Assets:Checking  -5.00 USD\n  Expenses:Uncategorized\n\n"
    )
    new = edit_source(source, txn, payee=payee)
    assert new.split("\n") == [expected, *source.split("\n")[1:]]
    # The edited source loads with the new payee.
    assert next(filter_txns(load_file(new + "\n"))).payee == payee


def test_edit_source_sets_category_on_the_automatic_posting_only(source_and_txn):
    ledger = (
        OPENS
        + """
2024-01-05 * "Coffee Shop" "Latte"
  meta: "kept"
  ! Assets:Checking  -5.00 USD ; paid
  ! Expenses:Uncategorized ; was unknown

"""
    )
    source, txn = source_and_txn(ledger)
    new = edit_source(source, txn, account="Expenses:Coffee")
    assert new == source.replace(
        "! Expenses:Uncategorized ; was unknown", "! Expenses:Coffee ; was unknown"
    )


def test_edit_source_without_changes_returns_the_source(source_and_txn):
    source, txn = source_and_txn(
        OPENS
        + '\n2024-01-05 * "Coffee Shop" "Latte"\n  Assets:Checking  -5.00 USD\n'
        + "  Expenses:Uncategorized\n\n"
    )
    assert edit_source(source, txn) == source
    assert edit_source(source, txn, payee="Coffee Shop", account="Expenses:Uncategorized") == (
        source
    )


def test_edit_source_ignores_category_without_a_single_automatic_posting(source_and_txn):
    source, txn = source_and_txn(
        OPENS
        + '\n2024-01-05 * "Coffee Shop" "Latte"\n  Assets:Checking  -5.00 USD\n'
        + "  Expenses:Uncategorized  5.00 USD\n\n"
    )
    assert edit_source(source, txn, account="Expenses:Coffee") == source


def test_plan_edits(load_file):
    entries = load_file(LEDGER.replace('"Espresso"', '"Espresso"\n  plaid_payee: "Coffee Shop"'))
    plans = plan_edits(
        entries, payee_regex="coffee", payee="{plaid_payee}", account="Expenses:Coffee"
    )
    assert [(p.txn.payee, p.payee, p.account, p.changes) for p in plans] == [
        ("Coffee Shop", None, "Expenses:Coffee", True),  # no plaid_payee to fill in
        ("COFFEE SHOP #12", "Coffee Shop", "Expenses:Coffee", True),
    ]


def test_plan_edits_with_nothing_to_change(load_file):
    entries = load_file(LEDGER)
    [plan] = plan_edits(
        entries, payee_regex="grocer", payee="Grocer", account="Expenses:Uncategorized"
    )
    assert (plan.payee, plan.account, plan.changes) == (None, None, False)
