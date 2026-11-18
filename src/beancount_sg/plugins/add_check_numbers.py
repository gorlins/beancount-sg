"""Record check numbers from transaction narrations as metadata.

Banks usually describe a cleared check like ``CHECK #1042``. For a payment by
check, this plugin adds the number as ``check-no`` metadata, so checks can be
queried and reconciled by number:

    2024-03-04 * "CHECK #01042"
      Assets:Checking  -250.00 USD
      Expenses:Home:Repairs

becomes

    2024-03-04 * "CHECK #01042"
      check-no: "1042"
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
already has ``check-no`` metadata, e.g. set by hand, keeps it.

Older metadata keys, ``check_no`` and ``checknum``, are converted to
``check-no``: they're removed, and their number becomes ``check-no`` unless the
transaction already has one. They're only converted if every number agrees,
compared as integers (so ``"01042"`` matches ``1042``): the legacy values, the
existing ``check-no``, or else the number in the narration. Otherwise the
transaction is left as it is, with an error naming each number and where it came
from.

Usage::

    plugin "beancount_sg.plugins.add_check_numbers"
"""

from __future__ import annotations

import functools
import re
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple

from beancount.core.account_types import get_account_type
from beancount.core.data import Directive, Meta, Transaction
from beancount.parser.options import get_account_types

from .plugin_helpers import flat_map_transactions

__plugins__ = ("add_check_numbers",)

META_KEY = "check-no"
# Older keys for the check number, converted to META_KEY.
LEGACY_KEYS = ("check_no", "checknum")
# The label for a check number read from the narration, in errors.
NARRATION = "narration"

# The word "check", then anything up to "#<number>".
_CHECK_NUMBER = re.compile(r"\bcheck\b[^#]*#(\d+)", re.IGNORECASE)


def add_check_numbers(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Add ``check-no`` metadata to payments by check."""
    # Root account names checks can be written from, e.g. {"Assets", "Liabilities"}.
    account_types = get_account_types(options_map)
    paying_roots = frozenset({account_types.assets, account_types.liabilities})
    return flat_map_transactions(
        entries, functools.partial(record_check_number, paying_roots=paying_roots)
    )


class CheckNumberError(NamedTuple):
    """Conforms to `beancount.core.data.BeancountError`."""

    source: Meta
    message: str
    entry: Transaction


def record_check_number(
    txn: Transaction, *, paying_roots: frozenset[str]
) -> tuple[list[Transaction], list[CheckNumberError]]:
    """The transaction with its check number recorded, and any error.

    Records the number of a payment by check, and converts legacy keys (see the
    module docstring).
    """
    current = txn.meta.get(META_KEY)
    # The check number, from check-no or else the narration, labelled by its source.
    expected: dict[str, object] = {}
    if current is not None:
        expected[META_KEY] = current
    elif (from_narration := get_check_number(txn, paying_roots)) is not None:
        expected[NARRATION] = from_narration
    legacy = {key: txn.meta[key] for key in LEGACY_KEYS if key in txn.meta}
    if not legacy:
        if NARRATION in expected:
            # Beancount metadata can't hold a plain int, so store the number as a string.
            return [txn._replace(meta={**txn.meta, META_KEY: expected[NARRATION]})], []
        return [txn], []

    sources = {**legacy, **expected}
    numbers = {_as_int(value) for value in sources.values()}
    if len(numbers) != 1 or None in numbers:
        found = ", ".join(f"{key} {str(value)!r}" for key, value in sources.items())
        message = f"Mismatched check numbers: {found}"
        return [txn], [CheckNumberError(txn.meta, message, txn)]
    [number] = numbers
    meta = {key: value for key, value in txn.meta.items() if key not in LEGACY_KEYS}
    meta[META_KEY] = current if current is not None else str(number)
    return [txn._replace(meta=meta)], []


def _as_int(value: object) -> int | None:
    """A metadata value as a whole number, e.g. ``"01042"`` or ``Decimal(1042)``, or None."""
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return int(number)


def get_check_number(txn: Transaction, paying_roots: frozenset[str]) -> str | None:
    """The check number if ``txn`` is a payment by check, else None.

    ``paying_roots`` are the root account names a check can be written from.
    """
    match = _CHECK_NUMBER.search(txn.narration or "")
    if match is None:
        return None
    # The check is written from exactly one asset or liability account.
    paying = [
        posting
        for posting in txn.postings
        if get_account_type(posting.account) in paying_roots and posting.units.number < 0
    ]
    if len(paying) != 1:
        return None
    return str(int(match.group(1)))
