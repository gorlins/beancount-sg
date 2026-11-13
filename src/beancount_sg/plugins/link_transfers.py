"""Link the two sides of a transfer.

Transactions posting the same amount (with opposite signs) to the configured
account (or its subaccounts) on the same day are linked, e.g. a withdrawal from
checking and the matching deposit into savings, both booked against a
``Assets:Transfers`` clearing account. See `beancount_sg.linking.Linker` for
details.

Usage::

    plugin "beancount_sg.plugins.link_transfers" "Assets:Transfers"
"""

from __future__ import annotations

from typing import Any

from beancount.core.data import Directive

from beancount_sg.linking import Linker

__plugins__ = ("link_transfers",)


def link_transfers(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Link same-day, same-amount transactions in the ``config`` account that cancel out."""
    if not config:
        raise ValueError('link_transfers requires an account, e.g. "Assets:Transfers"')
    return Linker(config)(entries), []
