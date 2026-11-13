"""Set each transaction's flag from its postings' flags.

A transaction is flagged ``!`` if any of its postings is flagged ``!``, and
``*`` otherwise. Unflagged postings are ignored, so a transaction with no
``!`` postings becomes ``*``. Only transactions flagged ``*`` or ``!`` are
changed; special flags such as ``P`` (padding) are preserved.

Posting flags are typically set by other plugins (for example
``beancount_sg.plugins.flag_balanced``), so list this plugin after them.

Usage::

    plugin "beancount_sg.plugins.flag_from_postings"
"""

from __future__ import annotations

from typing import Any

from beancount.core.data import Directive, Transaction
from beancount.core.flags import FLAG_OKAY, FLAG_WARNING

__plugins__ = ("flag_from_postings",)


def flag_from_postings(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Set transaction flags from posting flags."""
    new_entries = [
        flag_transaction(entry) if isinstance(entry, Transaction) else entry for entry in entries
    ]
    return new_entries, []


def flag_transaction(txn: Transaction) -> Transaction:
    """Return the transaction flagged from its postings; unchanged ones are returned as-is."""
    if txn.flag not in (FLAG_OKAY, FLAG_WARNING):
        return txn
    any_warning = any(posting.flag == FLAG_WARNING for posting in txn.postings)
    flag = FLAG_WARNING if any_warning else FLAG_OKAY
    return txn if flag == txn.flag else txn._replace(flag=flag)
