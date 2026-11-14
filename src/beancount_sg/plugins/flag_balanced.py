"""Flag postings according to whether a balance assertion covers them.

A balance assertion dated ``D`` checks an account's balance at the *start* of
``D``, so it verifies every posting to that account in that currency dated
strictly before ``D``.

For every posting whose account and currency have at least one balance
assertion on that exact account (assertions on parent accounts don't count),
this plugin sets the posting flag to ``*`` if it is dated before the latest
such assertion, or ``!`` if it is not yet covered. All other postings, posting
flags other than ``*``/``!``, and transaction flags are left alone; use
``beancount_sg.plugins.flag_from_postings`` to set transaction flags.

Usage::

    plugin "beancount_sg.plugins.flag_balanced"
"""

from __future__ import annotations

import datetime
import functools
from typing import Any

from beancount.core.data import Balance, Directive, Transaction
from beancount.core.flags import FLAG_OKAY, FLAG_WARNING

from .plugin_helpers import map_transactions

__plugins__ = ("flag_balanced",)

_MANAGED_FLAGS = frozenset({None, FLAG_OKAY, FLAG_WARNING})

BalanceDates = dict[tuple[str, str], datetime.date]


def flag_balanced(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Set posting flags based on balance-assertion coverage."""
    latest = latest_balance_dates(entries)
    if not latest:
        return entries, []
    return map_transactions(entries, functools.partial(flag_postings, latest=latest))


def latest_balance_dates(entries: list[Directive]) -> BalanceDates:
    """Map each asserted (account, currency) to the date of its latest balance assertion."""
    latest: BalanceDates = {}
    for entry in entries:
        if isinstance(entry, Balance):
            key = (entry.account, entry.amount.currency)
            if key not in latest or entry.date > latest[key]:
                latest[key] = entry.date
    return latest


def flag_postings(txn: Transaction, latest: BalanceDates) -> Transaction:
    """Return the transaction with its posting flags set; unchanged ones are returned as-is."""
    postings = list(txn.postings)
    any_changed = False
    for i, posting in enumerate(postings):
        if posting.flag not in _MANAGED_FLAGS or posting.units is None:
            continue
        covered_until = latest.get((posting.account, posting.units.currency))
        if covered_until is None:
            continue
        flag = FLAG_OKAY if txn.date < covered_until else FLAG_WARNING
        if posting.flag != flag:
            postings[i] = posting._replace(flag=flag)
            any_changed = True
    return txn._replace(postings=postings) if any_changed else txn
