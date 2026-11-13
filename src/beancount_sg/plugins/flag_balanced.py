"""Flag transactions according to whether a balance assertion covers them.

A balance assertion dated ``D`` checks an account's balance at the *start* of
``D``, so it verifies every posting to that account (or any of its
subaccounts) in that currency dated strictly before ``D``.

For every posting whose account and currency have at least one balance
assertion (on the account itself or on one of its parents), this plugin sets:

* the posting flag to ``*`` if it is dated before the latest such assertion,
  or ``!`` if it is not yet covered;
* the transaction flag to ``!`` if any of these postings is uncovered,
  otherwise ``*``.

Postings in accounts/currencies that never have a balance assertion are left
alone, and transactions with none of these postings are not modified. Only
transactions flagged ``*`` or ``!`` are touched; special flags such as
``P`` (padding) are preserved.

Usage::

    plugin "beancount_sg.plugins.flag_balanced"
"""

from __future__ import annotations

import datetime
from typing import Any

from beancount.core import account as account_lib
from beancount.core.data import Balance, Directive, Posting, Transaction
from beancount.core.flags import FLAG_OKAY, FLAG_WARNING

__plugins__ = ("flag_balanced",)

_MANAGED_FLAGS = frozenset({None, FLAG_OKAY, FLAG_WARNING})


def flag_balanced(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Set posting and transaction flags based on balance-assertion coverage."""
    latest: dict[tuple[str, str], datetime.date] = {}
    for entry in entries:
        if isinstance(entry, Balance):
            key = (entry.account, entry.amount.currency)
            if key not in latest or entry.date > latest[key]:
                latest[key] = entry.date

    if not latest:
        return entries, []

    def coverage(posting: Posting) -> datetime.date | None:
        """Latest assertion date covering this posting, or None if untracked."""
        if posting.units is None:
            return None
        dates = [
            latest[key]
            for acct in account_lib.parents(posting.account)
            if (key := (acct, posting.units.currency)) in latest
        ]
        return max(dates, default=None)

    new_entries = []
    for entry in entries:
        if isinstance(entry, Transaction) and entry.flag in _MANAGED_FLAGS:
            entry = _flag_transaction(entry, coverage)
        new_entries.append(entry)
    return new_entries, []


def _flag_transaction(txn: Transaction, coverage) -> Transaction:
    postings = list(txn.postings)
    tracked = False
    all_covered = True
    for i, posting in enumerate(postings):
        if posting.flag not in _MANAGED_FLAGS:
            continue
        covered_until = coverage(posting)
        if covered_until is None:
            continue
        tracked = True
        covered = txn.date < covered_until
        all_covered &= covered
        flag = FLAG_OKAY if covered else FLAG_WARNING
        if posting.flag != flag:
            postings[i] = posting._replace(flag=flag)

    if not tracked:
        return txn
    flag = FLAG_OKAY if all_covered else FLAG_WARNING
    if flag == txn.flag and all(a is b for a, b in zip(postings, txn.postings, strict=True)):
        return txn
    return txn._replace(flag=flag, postings=postings)
