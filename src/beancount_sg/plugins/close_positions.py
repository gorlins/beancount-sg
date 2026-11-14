"""Assert that a position is fully closed, and close its account.

When you sell all of a holding, such as every share of a stock or mutual fund,
the account holding it should be empty afterwards. Mark the selling posting
with ``closing: TRUE`` metadata:

    2024-06-03 * "Sell all VTI"
      Assets:Brokerage:VTI   -25 VTI {210.00 USD} @ 265.40 USD
        closing: TRUE
      Assets:Brokerage:Cash  6635.00 USD
      Income:Brokerage:Gains

and this plugin adds, dated the following day:

    2024-06-04 balance Assets:Brokerage:VTI  0 VTI
    2024-06-04 close Assets:Brokerage:VTI

A balance is checked at the start of its date, so the assertion verifies the
position right after the trade; if anything is left, Beancount reports a
balance error at the closing posting.

The account is only closed if it holds just that security, which is recognized
by its leaf being the commodity name, as in ``Assets:Brokerage:VTI`` holding
``VTI``. For an account holding several securities, like ``Assets:Brokerage``,
only the balance assertion for the sold commodity is added.

Only sales are supported: a closing posting must reduce a position held at
cost, i.e. have a cost basis (``{...}``) and negative units. Any other posting
marked ``closing`` (cash, a purchase, a conversion at a price) produces an
error and nothing is added for it, since closing its account would be wrong.

Every closing posting in a transaction is handled, the ``closing`` metadata is
kept, and no balance or close is added if the ledger (or an earlier closing
posting) already has it. The same ``closing`` metadata is used by Beancount's
built-in ``beancount.plugins.check_closing``, which adds only the balance check.

Usage::

    plugin "beancount_sg.plugins.close_positions"
"""

from __future__ import annotations

import datetime
import functools
from typing import Any, NamedTuple

from beancount.core import account as account_lib
from beancount.core.data import (
    Balance,
    BeancountError,
    Close,
    Directive,
    Meta,
    Transaction,
    new_metadata,
)
from beancount.core.number import ZERO

from beancount_sg.builders import A, B

from .plugin_helpers import flat_map_transactions

__plugins__ = ("close_positions",)

META_KEY = "closing"


class ClosePositionError(NamedTuple):
    """Conforms to `beancount.core.data.BeancountError`."""

    source: Meta
    message: str
    entry: Directive


def close_positions(
    entries: list[Directive], options_map: dict[str, Any]
) -> tuple[list[Directive], list[BeancountError]]:
    """Add a zero balance assertion and a close the day after each closing posting."""
    # Directives the ledger already has, so none are duplicated.
    closed = frozenset(entry.account for entry in entries if isinstance(entry, Close))
    balances = frozenset(
        (entry.date, entry.account, entry.amount.currency)
        for entry in entries
        if isinstance(entry, Balance)
    )
    close_txn = functools.partial(close_transaction, closed=closed, balances=balances)
    return flat_map_transactions(entries, close_txn)


def close_transaction(
    txn: Transaction,
    *,
    closed: frozenset[str],
    balances: frozenset[tuple[datetime.date, str, str]],
) -> tuple[list[Directive], list[BeancountError]]:
    """The transaction plus a balance and close for each of its closing postings.

    ``closed`` and ``balances`` are the accounts closed and the balance assertions
    (date, account, currency) already in the ledger, which aren't added again.
    """
    directives: list[Directive] = [txn]
    errors: list[BeancountError] = []
    # Also skip ones added for an earlier closing posting in this transaction.
    added_closes: set[str] = set()
    added_balances: set[tuple[datetime.date, str, str]] = set()
    for posting in txn.postings:
        if not (posting.meta and posting.meta.get(META_KEY)):
            continue
        # Point the error or added directives at the closing posting's source line.
        meta = new_metadata(
            posting.meta.get("filename", "<close_positions>"), posting.meta.get("lineno", 0)
        )
        # Only a sale out of a position held at cost can close it.
        if posting.cost is None or posting.units.number >= 0:
            errors.append(
                ClosePositionError(
                    meta,
                    f"'{META_KEY}' is only for sales of a position held at cost; "
                    f"{posting.account} {posting.units} isn't one",
                    txn,
                )
            )
            continue
        date = txn.date + datetime.timedelta(days=1)
        currency = posting.units.currency
        balance = (date, posting.account, currency)
        if balance not in balances and balance not in added_balances:
            added_balances.add(balance)
            directives.append(B(date, posting.account, A(ZERO, currency), meta=meta))
        # Close the account only if it holds just this commodity.
        if (
            account_lib.leaf(posting.account) == currency
            and posting.account not in closed
            and posting.account not in added_closes
        ):
            added_closes.add(posting.account)
            directives.append(Close(meta, date, posting.account))
    return directives, errors
