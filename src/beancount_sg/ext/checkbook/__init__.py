"""A Fava report listing checks, i.e. transactions with ``check_no`` metadata.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.checkbook"

The "Checkbook" report shows, for each check in the current Fava filter: its
date, number, payee and narration, the account it was written from, the
category it was spent on, and the amount. ``check_no`` metadata can be added
automatically with ``beancount_sg.plugins.add_check_numbers``.

- The account is the one Assets or Liabilities posting that's negative, as in
  ``add_check_numbers``; it's left blank if there isn't exactly one.
- The category is the other posting's account, or ``<split>`` if there are
  several.
- The amount is the positive amount paid, in that account's currency.
"""

from __future__ import annotations

from collections.abc import Iterable

from beancount.core.account_types import get_account_type
from beancount.core.data import Directive, Transaction
from fava.context import g
from fava.core.query import (
    AmountColumn,
    DateColumn,
    IntColumn,
    QueryResultTable,
    StrColumn,
)
from fava.ext import FavaExtensionBase

from beancount_sg.plugins.add_check_numbers import META_KEY

SPLIT = "<split>"
_MAX_TEXT = 32

COLUMNS = [
    DateColumn("date"),
    IntColumn("check_no"),
    StrColumn("payee"),
    StrColumn("account"),
    StrColumn("category"),
    StrColumn("narration"),
    AmountColumn("amount"),
]


class Checkbook(FavaExtensionBase):
    """Fava report listing the checks in the current filter."""

    report_title = "Checkbook"

    def table(self) -> QueryResultTable:
        """The checks in Fava's currently filtered entries."""
        roots = frozenset(
            {self.ledger.options["name_assets"], self.ledger.options["name_liabilities"]}
        )
        return checkbook_table(g.filtered.entries, roots)


def checkbook_table(entries: Iterable[Directive], paying_roots: frozenset[str]) -> QueryResultTable:
    """A row per transaction with check_no metadata, in entry order.

    ``paying_roots`` are the root account names a check can be written from.
    """
    rows = []
    for txn in entries:
        if not isinstance(txn, Transaction) or txn.meta.get(META_KEY) is None:
            continue
        paying = [
            posting
            for posting in txn.postings
            if get_account_type(posting.account) in paying_roots and posting.units.number < 0
        ]
        paid = paying[0] if len(paying) == 1 else None
        others = [posting.account for posting in txn.postings if posting is not paid]
        row = (
            txn.date,
            _check_number(txn.meta[META_KEY]),
            _truncate(txn.payee),
            paid.account if paid else None,
            others[0] if len(others) == 1 else SPLIT,
            _truncate(txn.narration),
            -paid.units if paid else None,
        )
        # Fava's table expects values in its serialised form, e.g. for amounts.
        rows.append(
            tuple(column.serialise(value) for column, value in zip(COLUMNS, row, strict=True))
        )
    return QueryResultTable(COLUMNS, rows)


def _check_number(value: object) -> int | None:
    """The check number as an int (it may be stored as a string or a number)."""
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _truncate(text: str | None) -> str | None:
    """Shorten long text so table columns stay narrow."""
    if text and len(text) > _MAX_TEXT:
        return text[: _MAX_TEXT - 3] + "..."
    return text
