from typing import NamedTuple

from beancount.core.data import Directive, Meta, Note
from beancount.core.flags import FLAG_OKAY, FLAG_WARNING

from beancount_sg.builders import A, B, P, T
from beancount_sg.plugins._transform import flat_map_transactions, map_transactions


class Error(NamedTuple):
    source: Meta
    message: str
    entry: Directive


BALANCE = B("2020-01-01", "Assets:Cash", A(0, "USD"))
NOTE = Note({}, BALANCE.date, "Assets:Cash", "a note", None, None)
FIRST = T("2020-01-02", narration="first", postings=[P("Assets:Cash", A(1, "USD"))])
SECOND = T("2020-01-03", narration="second", postings=[P("Assets:Cash", A(2, "USD"))])
ENTRIES = [BALANCE, FIRST, NOTE, SECOND]


def test_map_transactions_applies_fn_to_transactions_only():
    new_entries, errors = map_transactions(ENTRIES, lambda txn: txn._replace(flag=FLAG_WARNING))
    assert errors == []
    assert new_entries == [
        BALANCE,
        FIRST._replace(flag=FLAG_WARNING),
        NOTE,
        SECOND._replace(flag=FLAG_WARNING),
    ]


def test_map_transactions_keeps_unchanged_transactions():
    new_entries, _ = map_transactions(ENTRIES, lambda txn: txn)
    assert new_entries == ENTRIES


def test_flat_map_transactions_replaces_each_transaction_with_its_directives():
    def expand(txn):
        if txn.narration == "first":
            return [txn, B(txn.date, "Assets:Cash", A(1, "USD"))], []
        return [], []  # drop the second

    new_entries, errors = flat_map_transactions(ENTRIES, expand)
    assert errors == []
    assert new_entries == [BALANCE, FIRST, B(FIRST.date, "Assets:Cash", A(1, "USD")), NOTE]


def test_flat_map_transactions_collects_errors_in_order():
    def check(txn):
        return [txn], [Error(txn.meta, f"problem with {txn.narration}", txn)]

    new_entries, errors = flat_map_transactions(ENTRIES, check)
    assert new_entries == ENTRIES
    assert [error.message for error in errors] == ["problem with first", "problem with second"]


def test_input_is_not_mutated():
    entries = list(ENTRIES)
    map_transactions(entries, lambda txn: txn._replace(flag=FLAG_OKAY))
    flat_map_transactions(entries, lambda txn: ([], []))
    assert entries == ENTRIES
