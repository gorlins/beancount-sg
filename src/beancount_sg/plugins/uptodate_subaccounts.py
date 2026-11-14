"""Extend Fava's up-to-date indicator from an account to its subaccounts.

Fava shows an up-to-date indicator next to accounts whose ``open`` directive
has ``fava-uptodate-indication: TRUE`` metadata. Rather than marking every
subaccount, e.g. one per security under a brokerage account, mark the parent:

    2020-01-01 open Assets:Brokerage
      fava-uptodate-indication: TRUE
    2020-01-01 open Assets:Brokerage:VTI
    2020-01-01 open Assets:Brokerage:BND

and this plugin adds the metadata to the ``open`` of each direct subaccount
(``Assets:Brokerage:VTI`` and ``Assets:Brokerage:BND``). Deeper descendants
aren't affected unless their own parent is marked. A subaccount that sets the
metadata itself, e.g. to ``FALSE`` to opt out, keeps its own value.

Usage::

    plugin "beancount_sg.plugins.uptodate_subaccounts"
"""

from __future__ import annotations

from typing import Any

from beancount.core import account as account_lib
from beancount.core.data import Directive, Open

__plugins__ = ("uptodate_subaccounts",)

META_KEY = "fava-uptodate-indication"


def uptodate_subaccounts(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Mark the opens of direct subaccounts of marked accounts as up-to-date tracked."""
    marked = {
        entry.account for entry in entries if isinstance(entry, Open) and entry.meta.get(META_KEY)
    }
    new_entries = [
        mark_open(entry)
        if isinstance(entry, Open) and account_lib.parent(entry.account) in marked
        else entry
        for entry in entries
    ]
    return new_entries, []


def mark_open(entry: Open) -> Open:
    """The open with the up-to-date metadata added, unless it already sets it."""
    if META_KEY in entry.meta:
        return entry
    return entry._replace(meta={**entry.meta, META_KEY: True})
