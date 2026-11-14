"""Record check numbers from transaction narrations as metadata.

Banks usually describe a cleared check like ``CHECK #1042``. For a payment
whose narration mentions a check (or a note) and a ``#<number>``, this plugin
adds the number as ``check_no`` metadata, so checks can be queried and
reconciled by number:

    2024-03-04 * "CHECK #01042"
      Assets:Checking  -250.00 USD
      Expenses:Home:Repairs

becomes

    2024-03-04 * "CHECK #01042"
      check_no: "1042"
      Assets:Checking  -250.00 USD
      Expenses:Home:Repairs

A transaction counts as a payment by check when:

- its narration contains the word ``check`` or ``note`` (any case, whole words
  only, so ``Checking`` doesn't count), and
- its first posting is negative, i.e. money leaving the account that is listed
  first, as importers usually do.

The number is stored as a string without leading zeros. A transaction that
already has ``check_no`` metadata, e.g. set by hand, is left alone.

Usage::

    plugin "beancount_sg.plugins.check_numbers"
"""

from __future__ import annotations

import re
from typing import Any

from beancount.core.data import Directive, Transaction

from .plugin_helpers import map_transactions

__plugins__ = ("check_numbers",)

META_KEY = "check_no"

_CHECK_WORD = re.compile(r"\b(check|note)\b", re.IGNORECASE)
_CHECK_NUMBER = re.compile(r"#(\d+)")


def check_numbers(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Add ``check_no`` metadata to payments by check."""
    return map_transactions(entries, add_check_number)


def add_check_number(txn: Transaction) -> Transaction:
    """The transaction with its check number recorded, if it's a payment by check."""
    if META_KEY in txn.meta or not is_check_payment(txn):
        return txn
    match = _CHECK_NUMBER.search(txn.narration)
    if match is None:
        return txn
    # Beancount metadata can't hold a plain int, so store the number as a string.
    return txn._replace(meta={**txn.meta, META_KEY: str(int(match.group(1)))})


def is_check_payment(txn: Transaction) -> bool:
    """Whether the narration mentions a check or note and the first posting is negative."""
    return (
        bool(txn.postings)
        and txn.postings[0].units.number < 0
        and _CHECK_WORD.search(txn.narration or "") is not None
    )
