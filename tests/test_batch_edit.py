import re

import pytest
from beancount import loader
from beancount.core.data import filter_txns
from fava.core.file import get_entry_slice

from beancount_sg.batch_edit import (
    EditError,
    PlannedEdit,
    apply_edits,
    automatic_posting,
    find_transactions,
    new_payee,
    plan_edits,
    rewrite_entry,
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
        ("Store {store:04}", "Store 0012"),  # format specs work on metadata values
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
def test_rewrite_entry_sets_payee_and_keeps_the_rest(
    source_and_txn, load_file, header, payee, expected
):
    source, txn = source_and_txn(
        OPENS + f"\n{header}\n  Assets:Checking  -5.00 USD\n  Expenses:Uncategorized\n\n"
    )
    new = rewrite_entry(source, txn, payee=payee)
    assert new.split("\n") == [expected, *source.split("\n")[1:]]
    # The edited source loads with the new payee.
    assert next(filter_txns(load_file(new + "\n"))).payee == payee


def test_rewrite_entry_sets_category_on_the_automatic_posting_only(source_and_txn):
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
    new = rewrite_entry(source, txn, category="Expenses:Coffee")
    assert new == source.replace(
        "! Expenses:Uncategorized ; was unknown", "! Expenses:Coffee ; was unknown"
    )


def test_rewrite_entry_without_changes_returns_the_source(source_and_txn):
    source, txn = source_and_txn(
        OPENS
        + '\n2024-01-05 * "Coffee Shop" "Latte"\n  Assets:Checking  -5.00 USD\n'
        + "  Expenses:Uncategorized\n\n"
    )
    assert rewrite_entry(source, txn) == source
    assert rewrite_entry(source, txn, payee="Coffee Shop", category="Expenses:Uncategorized") == (
        source
    )


def test_rewrite_entry_ignores_category_without_a_single_automatic_posting(source_and_txn):
    source, txn = source_and_txn(
        OPENS
        + '\n2024-01-05 * "Coffee Shop" "Latte"\n  Assets:Checking  -5.00 USD\n'
        + "  Expenses:Uncategorized  5.00 USD\n\n"
    )
    assert rewrite_entry(source, txn, category="Expenses:Coffee") == source


def test_plan_edits(load_file):
    entries = load_file(LEDGER.replace('"Espresso"', '"Espresso"\n  plaid_payee: "Coffee Shop"'))
    plans = plan_edits(
        entries, payee_regex="coffee", payee="{plaid_payee}", category="Expenses:Coffee"
    )
    assert [(p.txn.payee, p.payee, p.category, p.changes) for p in plans] == [
        ("Coffee Shop", None, "Expenses:Coffee", True),  # no plaid_payee to fill in
        ("COFFEE SHOP #12", "Coffee Shop", "Expenses:Coffee", True),
    ]


def test_plan_edits_with_nothing_to_change(load_file):
    entries = load_file(LEDGER)
    [plan] = plan_edits(
        entries, payee_regex="grocer", payee="Grocer", category="Expenses:Uncategorized"
    )
    assert (plan.payee, plan.category, plan.changes) == (None, None, False)


@pytest.fixture
def ledger_file(tmp_path):
    """Write a ledger to a file and load it; returns the path and its transactions."""

    def ledger_file(ledger: str, newline: str = "\n"):
        path = tmp_path / "main.beancount"
        path.write_bytes(ledger.replace("\n", newline).encode())
        entries, errors, _ = loader.load_file(str(path))
        assert errors == []
        return path, list(filter_txns(entries))

    return ledger_file


FILE_LEDGER = OPENS + LEDGER


def test_apply_edits_writes_the_files(ledger_file):
    path, entries = ledger_file(FILE_LEDGER)
    edits = plan_edits(entries, payee_regex="coffee", payee="Cafe", category="Expenses:Coffee")
    result = apply_edits(edits)
    assert (len(result.changed), result.errors) == (2, [])
    assert path.read_text() == (
        FILE_LEDGER.replace('"Coffee Shop" "Latte"', '"Cafe" "Latte"')
        .replace('"COFFEE SHOP #12" "Espresso"', '"Cafe" "Espresso"')
        .replace("-5.00 USD\n  Expenses:Uncategorized", "-5.00 USD\n  Expenses:Coffee")
        .replace("-3.00 USD\n  Expenses:Uncategorized", "-3.00 USD\n  Expenses:Coffee")
    )


def test_apply_edits_skips_edits_without_changes(ledger_file):
    path, entries = ledger_file(FILE_LEDGER)
    result = apply_edits(plan_edits(entries, payee_regex="grocer", payee="Grocer"))
    assert (result.changed, result.errors) == ([], [])
    assert path.read_text() == FILE_LEDGER


def test_apply_edits_keeps_crlf_line_endings(ledger_file):
    path, entries = ledger_file(FILE_LEDGER, newline="\r\n")
    apply_edits(plan_edits(entries, payee_regex="grocer", payee="Market"))
    assert (
        path.read_bytes()
        == FILE_LEDGER.replace('"Grocer"', '"Market"').replace("\n", "\r\n").encode()
    )


def test_apply_edits_refuses_lines_that_moved_since_loading(ledger_file):
    path, entries = ledger_file(FILE_LEDGER)
    edits = plan_edits(entries, payee_regex="coffee", payee="Cafe")
    moved = "; a line added above everything\n" + FILE_LEDGER
    path.write_text(moved)
    result = apply_edits(edits)
    assert result.changed == []
    assert [edit.txn.narration for edit, _ in result.errors] == ["Latte", "Espresso"]
    assert "has the file changed since it was loaded?" in result.errors[0][1]
    assert path.read_text() == moved


def test_rewrite_entry_requires_the_transaction_text():
    txn = T("2024-01-05", payee="Old", meta={"lineno": 1})
    with pytest.raises(EditError, match="Expected the transaction dated 2024-01-05"):
        rewrite_entry('2024-01-06 * "Other"', txn, payee="New")


class RecordingBackend:
    """A backend that keeps entries' text in memory."""

    def __init__(self, texts):
        self.texts = texts
        self.writes = []

    def read_entry(self, txn):
        return self.texts[txn.narration]

    def write_entry(self, txn, old, new):
        if self.texts[txn.narration] != old:
            raise EditError("changed")
        self.texts[txn.narration] = new
        self.writes.append(txn.narration)


def test_apply_edits_uses_the_given_backend():
    txn = T(
        "2024-01-05",
        payee="Old",
        narration="Latte",
        meta={"lineno": 1},
        postings=[P("Expenses:Uncategorized", meta={"lineno": 2, "__automatic__": True})],
    )
    backend = RecordingBackend({"Latte": '2024-01-05 * "Old" "Latte"\n  Expenses:Uncategorized'})
    result = apply_edits([PlannedEdit(txn, payee="New", category="Expenses:Coffee")], backend)
    assert (len(result.changed), result.errors, backend.writes) == (1, [], ["Latte"])
    assert backend.texts["Latte"] == '2024-01-05 * "New" "Latte"\n  Expenses:Coffee'
