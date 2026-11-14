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
balance error at the closing posting. Because the account is closed too, this
is meant for accounts that hold a single security, e.g. one account per ticker.

Every closing posting in a transaction is handled, the ``closing`` metadata is
kept, and no balance or close is added if the ledger (or an earlier closing
posting) already has it. The same ``closing`` metadata is used by Beancount's
built-in ``beancount.plugins.check_closing``, which adds only the balance check.

Usage::

    plugin "beancount_sg.plugins.close_positions"
"""

from __future__ import annotations

import datetime
from typing import Any

from beancount.core.data import Balance, Close, Directive, Transaction, new_metadata
from beancount.core.number import ZERO

from ..builders import A, B

__plugins__ = ("close_positions",)

META_KEY = "closing"


def close_positions(
    entries: list[Directive], options_map: dict[str, Any]
) -> tuple[list[Directive], list[Any]]:
    """Add a zero balance assertion and a close the day after each closing posting."""
    # Directives the ledger already has, so none are duplicated.
    closed = {entry.account for entry in entries if isinstance(entry, Close)}
    balances = {
        (entry.date, entry.account, entry.amount.currency)
        for entry in entries
        if isinstance(entry, Balance)
    }

    new_entries = list(entries)
    for txn in entries:
        if not isinstance(txn, Transaction):
            continue
        for posting in txn.postings:
            if not (posting.meta and posting.meta.get(META_KEY)):
                continue
            date = txn.date + datetime.timedelta(days=1)
            meta = new_metadata(
                posting.meta.get("filename", "<close_positions>"), posting.meta.get("lineno", 0)
            )
            balance = (date, posting.account, posting.units.currency)
            if balance not in balances:
                balances.add(balance)
                new_entries.append(
                    B(date, posting.account, A(ZERO, posting.units.currency), meta=meta)
                )
            if posting.account not in closed:
                closed.add(posting.account)
                new_entries.append(Close(meta, date, posting.account))
    return new_entries, []
