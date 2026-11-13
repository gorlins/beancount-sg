"""Link the two sides of a transfer.

Transactions posting the same amount (with opposite signs) to the configured
account (or its subaccounts) are linked when they cancel out, e.g. a withdrawal
from checking and the matching deposit into savings, both booked against an
``Assets:Transfers`` clearing account.

Transfers often clear on different days, so matching runs in passes from the
tightest window to the loosest (see `PASSES`): same day, same week, same week
with dates shifted 3 days, same month, then same month shifted 3 days. The
shifted passes catch transfers that straddle a week or month boundary. A
transaction linked in an earlier pass keeps that link and isn't re-matched. See
`beancount_sg.plugins.linking.Linker` for how keys are built and matched.

Usage::

    plugin "beancount_sg.plugins.link_transfers" "Assets:Transfers"
"""

from __future__ import annotations

import datetime
from typing import Any

from beancount.core.data import Directive

from beancount_sg.plugins.linking import Linker

__plugins__ = ("link_transfers",)

_SHIFT = datetime.timedelta(days=3)

# (date_format, date_offset) for each matching pass, tightest first.
PASSES: list[tuple[str, datetime.timedelta | None]] = [
    ("%Y%m%d", None),
    ("%Yw%W", None),
    ("%Yw%W", _SHIFT),
    ("%Y%m", None),
    ("%Y%m", _SHIFT),
]


def link_transfers(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Link same-amount transactions in the ``config`` account that cancel out."""
    if not config:
        raise ValueError('link_transfers requires an account, e.g. "Assets:Transfers"')
    for date_format, date_offset in PASSES:
        entries = Linker(config, date_format=date_format, date_offset=date_offset)(entries)
    return entries, []
