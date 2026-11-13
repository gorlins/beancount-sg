"""Flag transactions according to whether a balance assertion covers them.

A balance assertion dated ``D`` checks an account's balance at the *start* of
``D``, so it verifies every posting to that account in that currency dated
strictly before ``D``.

For every posting whose account and currency have at least one balance
assertion on that exact account (assertions on parent accounts don't count),
this plugin sets:

* the posting flag to ``*`` if it is dated before the latest such assertion,
  or ``!`` if it is not yet covered;
* the transaction flag to ``!`` if any of these postings is uncovered,
  otherwise ``*``.

Postings in accounts/currencies without balance assertions are left alone,
and transactions with none of these postings are not modified. Posting flags
are managed regardless of the transaction flag, but the transaction flag is
only changed if it is ``*`` or ``!``; special flags such as ``P`` (padding)
are preserved. Postings with special flags are likewise left alone.

Usage::

    plugin "beancount_sg.plugins.flag_balanced"
"""

from __future__ import annotations

import datetime
from typing import Any

from beancount.core.data import Balance, Directive, Transaction
from beancount.core.flags import FLAG_OKAY, FLAG_WARNING

__plugins__ = ("flag_balanced",)

_MANAGED_FLAGS = frozenset({None, FLAG_OKAY, FLAG_WARNING})

BalanceDates = dict[tuple[str, str], datetime.date]


def flag_balanced(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Set posting and transaction flags based on balance-assertion coverage."""
    latest = latest_balance_dates(entries)
    if not latest:
        return entries, []
    new_entries = [
        flag_transaction(entry, latest) if isinstance(entry, Transaction) else entry
        for entry in entries
    ]
    return new_entries, []


def latest_balance_dates(entries: list[Directive]) -> BalanceDates:
    """Map each asserted (account, currency) to the date of its latest balance assertion."""
    latest: BalanceDates = {}
    for entry in entries:
        if isinstance(entry, Balance):
            key = (entry.account, entry.amount.currency)
            if key not in latest or entry.date > latest[key]:
                latest[key] = entry.date
    return latest


def flag_transaction(txn: Transaction, latest: BalanceDates) -> Transaction:
    """Return the transaction with its flags set; unchanged transactions are returned as-is."""
    postings = list(txn.postings)
    tracked = False
    all_covered = True
    any_changed = False
    for i, posting in enumerate(postings):
        if posting.flag not in _MANAGED_FLAGS or posting.units is None:
            continue
        covered_until = latest.get((posting.account, posting.units.currency))
        if covered_until is None:
            continue
        tracked = True
        covered = txn.date < covered_until
        all_covered &= covered
        flag = FLAG_OKAY if covered else FLAG_WARNING
        if posting.flag != flag:
            postings[i] = posting._replace(flag=flag)
            any_changed = True

    if not tracked:
        return txn
    flag = txn.flag
    if flag in _MANAGED_FLAGS:
        flag = FLAG_OKAY if all_covered else FLAG_WARNING
    if flag == txn.flag and not any_changed:
        return txn
    return txn._replace(flag=flag, postings=postings)
