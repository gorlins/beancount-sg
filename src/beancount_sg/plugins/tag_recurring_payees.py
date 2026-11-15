"""Tag every transaction from a payee once any of them is tagged recurring.

Tag one transaction from a payee as recurring, e.g. a subscription:

    2024-01-05 * "Netflix" "Subscription" #recurring
      Liabilities:CreditCard  -15.49 USD
      Expenses:Entertainment

and every other transaction with the same payee, earlier or later, gets the
tag too, so recurring spending can be filtered or reported on in one place.
Payees must match exactly. Transactions without a payee are never tagged.

The tag defaults to ``recurring``; pass another as the plugin config.

Usage::

    plugin "beancount_sg.plugins.tag_recurring_payees"
    plugin "beancount_sg.plugins.tag_recurring_payees" "subscription"
"""

from __future__ import annotations

import functools
from typing import Any

from beancount.core.data import Directive, Transaction, filter_txns

from .plugin_helpers import map_transactions

__plugins__ = ("tag_recurring_payees",)

DEFAULT_TAG = "recurring"


def tag_recurring_payees(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Tag all transactions from payees that have at least one tagged transaction."""
    tag = config or DEFAULT_TAG
    payees = frozenset(
        txn.payee for txn in filter_txns(entries) if txn.payee and tag in (txn.tags or ())
    )
    return map_transactions(entries, functools.partial(tag_payee, payees=payees, tag=tag))


def tag_payee(txn: Transaction, *, payees: frozenset[str], tag: str) -> Transaction:
    """The transaction with ``tag`` added if its payee is one of ``payees``."""
    tags = txn.tags or frozenset()
    if txn.payee not in payees or tag in tags:
        return txn
    return txn._replace(tags=tags | {tag})
