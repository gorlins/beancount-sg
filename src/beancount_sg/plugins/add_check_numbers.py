"""Record check numbers from transaction narrations as metadata.

Banks usually describe a cleared check like ``CHECK #1042``. For a payment by
check, this plugin adds the number as ``check_no`` metadata, so checks can be
queried and reconciled by number:

    2024-03-04 * "CHECK #01042"
      Assets:Checking  -250.00 USD
      Expenses:Home:Repairs

becomes

    2024-03-04 * "CHECK #01042"
      check_no: "1042"
      Assets:Checking  -250.00 USD
      Expenses:Home:Repairs

A transaction counts as a payment by check when:

- its narration has the word ``check`` (any case, whole word, so ``Checking``
  doesn't count) followed by ``#<number>``, e.g. ``CHECK #1042`` or
  ``Check paid #1042``; and
- exactly one of its postings to an Assets or Liabilities account is negative,
  the account the check was written from. Liabilities are included for checks
  written against e.g. a line of credit. Posting order doesn't matter.

The number is stored as a string without leading zeros. A transaction that
already has ``check_no`` metadata, e.g. set by hand, is left alone.

Usage::

    plugin "beancount_sg.plugins.add_check_numbers"
"""

from __future__ import annotations

import functools
import re
from typing import Any

from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Directive, Transaction
from beancount.parser.options import get_account_types

from .plugin_helpers import map_transactions

__plugins__ = ("add_check_numbers",)

META_KEY = "check_no"

# The word "check", then anything up to "#<number>".
_CHECK_NUMBER = re.compile(r"\bcheck\b[^#]*#(\d+)", re.IGNORECASE)


def add_check_numbers(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Add ``check_no`` metadata to payments by check."""
    account_types = get_account_types(options_map)
    return map_transactions(
        entries, functools.partial(record_check_number, account_types=account_types)
    )


def record_check_number(txn: Transaction, *, account_types: AccountTypes) -> Transaction:
    """The transaction with its check number recorded, if it's a payment by check."""
    if META_KEY in txn.meta:
        return txn
    number = get_check_number(txn, account_types)
    if number is None:
        return txn
    # Beancount metadata can't hold a plain int, so store the number as a string.
    return txn._replace(meta={**txn.meta, META_KEY: number})


def get_check_number(txn: Transaction, account_types: AccountTypes) -> str | None:
    """The check number if ``txn`` is a payment by check, else None."""
    match = _CHECK_NUMBER.search(txn.narration or "")
    if match is None:
        return None
    # The check is written from exactly one asset or liability account.
    balance_sheet = {account_types.assets, account_types.liabilities}
    paying = [
        posting
        for posting in txn.postings
        if get_account_type(posting.account) in balance_sheet and posting.units.number < 0
    ]
    if len(paying) != 1:
        return None
    return str(int(match.group(1)))
