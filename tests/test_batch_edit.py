"""Tests for the batch editing core, without Fava (see tests/ext for the Fava report)."""

import re

import pytest
from beancount import loader
from beancount.core.data import filter_txns

from beancount_sg.batch_edit import (
    SPLIT,
    EditError,
    FileBackend,
    PlannedEdit,
    apply_edits,
    category_posting,
    current_category,
    find_transactions,
    new_payee,
    plan_edits,
    rewrite_entry,
)
from beancount_sg.builders import A, P, T

OPENS = """
2020-01-01 open Assets:Checking
2020-01-01 open Assets:Savings
2020-01-01 open Expenses:Uncategorized
2020-01-01 open Expenses:Coffee
2020-01-01 open Expenses:Food
2020-01-01 open Income:Refunds
"""

LEDGER = (
    OPENS
    + """
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
)


@pytest.fixture
def ledger_file(tmp_path):
    """Write a ledger to a real file and load it; returns the path and its transactions.

    Transactions loaded from a file can be edited (unlike ones from a string).
    """

    def ledger_file(ledger: str, newline: str = "\n"):
        path = tmp_path / "main.beancount"
        path.write_bytes(ledger.replace("\n", newline).encode())
        entries, errors, _ = loader.load_file(str(path))
        assert errors == []
        return path, list(filter_txns(entries))

    return ledger_file


def entry(ledger_file, transaction: str):
    """A single transaction's text as read from its file, and the loaded transaction."""
    _, [txn] = ledger_file(OPENS + "\n" + transaction + "\n")
    return FileBackend().read_entry(txn), txn


# find_transactions


def payees(found):
    return [txn.payee for txn in found]


def test_find_by_payee_is_case_insensitive_and_anchored_at_the_start(ledger_file):
    _, txns = ledger_file(LEDGER)
    both = ["Coffee Shop", "COFFEE SHOP #12"]
    assert payees(find_transactions(txns, payee_regex="coffee shop")) == both
    assert payees(find_transactions(txns, payee_regex="shop")) == []
    assert payees(find_transactions(txns, payee_regex=".*shop")) == both


def test_find_by_narration_and_both(ledger_file):
    _, txns = ledger_file(LEDGER)
    assert payees(find_transactions(txns, narration_regex=".*coffee")) == ["Grocer"]
    assert payees(find_transactions(txns, payee_regex="coffee", narration_regex="esp")) == [
        "COFFEE SHOP #12"
    ]


def test_find_needs_a_pattern(ledger_file):
    _, txns = ledger_file(LEDGER)
    assert find_transactions(txns) == []


def test_find_skips_transactions_not_in_a_file(ledger_file, tmp_path):
    _, [written, *_] = ledger_file(LEDGER)
    generated = T("2024-01-05", payee="Coffee Shop", meta={"filename": "<pad>", "lineno": 0})
    missing = T("2024-01-05", payee="Coffee Shop", meta={"filename": str(tmp_path / "gone")})
    built = T("2024-01-05", payee="Coffee Shop")
    found = find_transactions([written, generated, missing, built], payee_regex="coffee")
    assert found == [written]


def test_find_rejects_invalid_patterns():
    with pytest.raises(re.error):
        find_transactions([], payee_regex="(")


# Categories


@pytest.mark.parametrize(
    ("postings", "category"),
    [
        ("  Assets:Checking  -5.00 USD\n  Expenses:Coffee", "Expenses:Coffee"),
        ("  Assets:Checking  -5.00 USD\n  Expenses:Coffee  5.00 USD", "Expenses:Coffee"),
        ("  Assets:Checking  5.00 USD\n  Income:Refunds", "Income:Refunds"),
        ("  Assets:Checking  -5.00 USD\n  Expenses:Coffee  3.00 USD\n  Expenses:Food", SPLIT),
        ("  Assets:Checking  -5.00 USD\n  Assets:Savings", None),  # a transfer
    ],
)
def test_current_category(ledger_file, postings, category):
    _, [txn] = ledger_file(OPENS + '\n2024-01-05 * "Shop"\n' + postings + "\n")
    assert current_category(txn) == category
    posting = category_posting(txn)
    assert (posting.account if posting else None) == (None if category == SPLIT else category)


# new_payee


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
        ("{blank}", None),  # filling in to an empty string means no change
    ],
)
def test_new_payee(template, expected):
    txn = T("2024-01-05", meta={"plaid_payee": "Starbucks Corp", "store": 12, "blank": ""})
    assert new_payee(txn, template) == expected


# plan_edits


def test_plan_edits(ledger_file):
    _, txns = ledger_file(LEDGER.replace('"Espresso"', '"Espresso"\n  plaid_payee: "Coffee Shop"'))
    plans = plan_edits(
        txns, payee_regex="coffee", payee="{plaid_payee}", category="Expenses:Coffee"
    )
    assert [(p.txn.payee, p.payee, p.category, p.changes) for p in plans] == [
        ("Coffee Shop", None, "Expenses:Coffee", True),  # no plaid_payee to fill in
        ("COFFEE SHOP #12", "Coffee Shop", "Expenses:Coffee", True),
    ]


@pytest.mark.parametrize(
    ("payee", "category"),
    [
        ("Grocer", "Expenses:Uncategorized"),  # the same as now
        ("", ""),  # empty: keep as is
    ],
)
def test_plan_edits_with_nothing_to_change(ledger_file, payee, category):
    _, txns = ledger_file(LEDGER)
    [plan] = plan_edits(txns, payee_regex="grocer", payee=payee, category=category)
    assert (plan.payee, plan.category, plan.changes) == (None, None, False)


SPLIT_ENTRY = (
    '2024-01-05 * "Coffee Shop" "Latte and a muffin"\n'
    "  Assets:Checking  -9.00 USD\n"
    "  Expenses:Coffee  5.00 USD\n"
    "  Expenses:Food"
)


def test_plan_edits_for_a_split_changes_only_the_payee(ledger_file):
    _, [txn] = ledger_file(OPENS + "\n" + SPLIT_ENTRY + "\n")
    [plan] = plan_edits([txn], payee_regex="coffee", payee="Cafe", category="Expenses:Coffee")
    assert (plan.payee, plan.category, plan.current_category) == ("Cafe", None, SPLIT)


# rewrite_entry

POSTINGS = "\n  Assets:Checking  -5.00 USD\n  Expenses:Uncategorized"


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
def test_rewrite_entry_sets_payee_and_keeps_the_rest(ledger_file, header, payee, expected):
    text, txn = entry(ledger_file, header + POSTINGS)
    new = rewrite_entry(text, txn, payee=payee)
    assert new.split("\n") == [expected, *text.split("\n")[1:]]
    # The rewritten text loads with the new payee.
    _, [reloaded] = ledger_file(OPENS + "\n" + new + "\n")
    assert reloaded.payee == payee


def test_rewrite_entry_sets_category_on_the_category_posting_only(ledger_file):
    text, txn = entry(
        ledger_file,
        '2024-01-05 * "Coffee Shop" "Latte"\n'
        '  meta: "kept"\n'
        "  ! Assets:Checking  -5.00 USD ; paid\n"
        "  ! Expenses:Uncategorized ; was unknown",
    )
    new = rewrite_entry(text, txn, category="Expenses:Coffee")
    assert new == text.replace(
        "! Expenses:Uncategorized ; was unknown", "! Expenses:Coffee ; was unknown"
    )


def test_rewrite_entry_without_changes_returns_the_text(ledger_file):
    text, txn = entry(ledger_file, '2024-01-05 * "Coffee Shop" "Latte"' + POSTINGS)
    assert rewrite_entry(text, txn) == text
    assert rewrite_entry(text, txn, payee="", category="") == text  # empty: keep as is
    assert rewrite_entry(text, txn, payee="Coffee Shop", category="Expenses:Uncategorized") == text


def test_rewrite_entry_sets_category_with_a_written_amount(ledger_file):
    text, txn = entry(
        ledger_file,
        '2024-01-05 * "Coffee Shop" "Latte"\n'
        "  Assets:Checking  -5.00 USD\n"
        "  Expenses:Uncategorized  5.00 USD",
    )
    new = rewrite_entry(text, txn, category="Expenses:Coffee")
    assert new == text.replace("Expenses:Uncategorized  5.00 USD", "Expenses:Coffee  5.00 USD")


def test_rewrite_entry_changes_a_splits_payee_but_not_its_category(ledger_file):
    text, txn = entry(ledger_file, SPLIT_ENTRY)
    new = rewrite_entry(text, txn, payee="Cafe", category="Expenses:Uncategorized")
    assert new == text.replace('"Coffee Shop"', '"Cafe"')


def test_rewrite_entry_finds_the_category_posting_by_its_line(ledger_file):
    text, txn = entry(ledger_file, '2024-01-05 * "Coffee Shop" "Latte"' + POSTINGS)
    # As if plugins had reordered the postings and added one that isn't in the file.
    added = P("Assets:Rounding", A("0.00", "USD"))
    shuffled = txn._replace(postings=[added, *reversed(txn.postings)])
    new = rewrite_entry(text, shuffled, category="Expenses:Coffee")
    assert new == text.replace("Expenses:Uncategorized", "Expenses:Coffee")


@pytest.mark.parametrize(
    "posting_line",
    [
        "  Expenses:Food",  # another account on the posting's line
        "  Expenses:Uncategorized  5.00 USD",  # an amount where none was written
        '  note: "added"\n  Expenses:Uncategorized',  # the posting moved to another line
    ],
)
def test_rewrite_entry_refuses_a_different_posting_on_the_line(ledger_file, posting_line):
    text, txn = entry(ledger_file, '2024-01-05 * "Coffee Shop" "Latte"' + POSTINGS)
    changed = text.replace("  Expenses:Uncategorized", posting_line)
    with pytest.raises(EditError, match="not its posting to Expenses:Uncategorized"):
        rewrite_entry(changed, txn, category="Expenses:Coffee")


@pytest.mark.parametrize(
    "text",
    [
        '2024-01-06 * "Old" "Latte"',  # another date
        '2024-01-05 * "Other" "Latte"',  # another payee
        '2024-01-05 * "Old" "Mocha"',  # another narration
        "  Assets:Checking  -5.00 USD",  # not the start of a transaction
    ],
)
def test_rewrite_entry_refuses_text_that_is_not_the_transaction(text):
    txn = T("2024-01-05", payee="Old", narration="Latte", meta={"lineno": 1})
    assert rewrite_entry('2024-01-05 * "Old" "Latte"', txn, payee="New") == (
        '2024-01-05 * "New" "Latte"'
    )
    with pytest.raises(EditError, match="Expected the transaction dated 2024-01-05"):
        rewrite_entry(text, txn, payee="New")


# apply_edits, with the default FileBackend


def test_apply_edits_writes_the_files(ledger_file):
    path, txns = ledger_file(LEDGER)
    edits = plan_edits(txns, payee_regex="coffee", payee="Cafe", category="Expenses:Coffee")
    result = apply_edits(edits)
    assert (len(result.changed), result.errors) == (2, [])
    assert path.read_text() == (
        LEDGER.replace('"Coffee Shop" "Latte"', '"Cafe" "Latte"')
        .replace('"COFFEE SHOP #12" "Espresso"', '"Cafe" "Espresso"')
        .replace("-5.00 USD\n  Expenses:Uncategorized", "-5.00 USD\n  Expenses:Coffee")
        .replace("-3.00 USD\n  Expenses:Uncategorized", "-3.00 USD\n  Expenses:Coffee")
    )


def test_apply_edits_skips_edits_without_changes(ledger_file):
    path, txns = ledger_file(LEDGER)
    result = apply_edits(plan_edits(txns, payee_regex="grocer", payee="Grocer"))
    assert (result.changed, result.errors) == ([], [])
    assert path.read_text() == LEDGER


def test_apply_edits_keeps_crlf_line_endings(ledger_file):
    path, txns = ledger_file(LEDGER, newline="\r\n")
    apply_edits(plan_edits(txns, payee_regex="grocer", payee="Market"))
    expected = LEDGER.replace('"Grocer"', '"Market"').replace("\n", "\r\n")
    assert path.read_bytes() == expected.encode()


def test_apply_edits_refuses_lines_that_moved_since_loading(ledger_file):
    path, txns = ledger_file(LEDGER)
    edits = plan_edits(txns, payee_regex="coffee", payee="Cafe")
    moved = "; a line added above everything\n" + LEDGER
    path.write_text(moved)
    result = apply_edits(edits)
    assert result.changed == []
    assert [edit.txn.narration for edit, _ in result.errors] == ["Latte", "Espresso"]
    assert "has the file changed since it was loaded?" in result.errors[0][1]
    assert path.read_text() == moved


# apply_edits, with another backend


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


# FileBackend


def test_file_backend_reads_from_the_first_line_through_the_last_posting(ledger_file):
    _, [txn, *_] = ledger_file(LEDGER.replace("-5.00 USD", '-5.00 USD\n    note: "posting meta"'))
    assert FileBackend().read_entry(txn) == (
        '2024-01-05 * "Coffee Shop" "Latte"\n'
        "  Assets:Checking  -5.00 USD\n"
        '    note: "posting meta"\n'
        "  Expenses:Uncategorized\n"
    )


def test_file_backend_refuses_text_that_changed(ledger_file):
    path, [txn, *_] = ledger_file(LEDGER)
    with pytest.raises(EditError, match="changed while editing"):
        FileBackend().write_entry(txn, "not the current text", "new text")
    assert path.read_text() == LEDGER
