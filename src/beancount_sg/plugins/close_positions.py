"""Assert that a position is fully closed, and close its account.

Some trades are known to close out a position: afterwards, the account should
hold none of that instrument. Options are the typical case, where each contract
is held in one lot and eventually expires or is sold off entirely. Mark such a
posting with ``closing: TRUE`` metadata:

    2018-02-16 * "SOLD -14 QQQ 100 16 FEB 18 160 CALL @5.31"
      Assets:Brokerage:Options:QQQ180216C160  -1400 QQQ180216C160 {2.70 USD} @ 5.31 USD
        closing: TRUE
      Assets:Brokerage:Cash                    7416.13 USD
      Income:Brokerage:PnL

and this plugin adds, dated the following day:

    2018-02-17 balance Assets:Brokerage:Options:QQQ180216C160  0 QQQ180216C160
    2018-02-17 close Assets:Brokerage:Options:QQQ180216C160

The balance assertion checks the position right after the trade (a balance is
checked at the start of its date), so a position that isn't actually closed is
reported as a balance error. Because the account is closed too, this is meant
for accounts that hold a single instrument.

Compared to Beancount's built-in ``beancount.plugins.check_closing``, this
plugin keeps the ``closing`` metadata, also closes the account, handles every
closing posting in a transaction, and doesn't add a balance or close that the
ledger (or an earlier closing posting) already has. The inserted directives
point at the closing posting's source line, so errors are reported there.

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
