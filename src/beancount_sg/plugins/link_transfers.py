"""Link the two sides of a transfer.

Transactions posting the same amount (with opposite signs) to the configured
account (or its subaccounts) are linked when they cancel out, e.g. a withdrawal
from checking and the matching deposit into savings, both booked against an
``Assets:Transfers`` clearing account. Matched postings are flagged ``*`` and
unmatched ones ``!``.

The two sides of a transfer often post on different days, so matching tries
progressively wider date windows (see `WINDOWS`); a transaction matched in a
tighter window isn't considered again. See `beancount_sg.plugins._linking.Linker`
for how keys are built and matched.

Usage::

    plugin "beancount_sg.plugins.link_transfers" "Assets:Transfers"
"""

from __future__ import annotations

import datetime
from typing import Any

from beancount.core.data import Directive

from ._linking import Linker, Window

__plugins__ = ("link_transfers",)

# Calendar windows split transfers that straddle a boundary: one sent on a Friday
# and received the next Monday lands in different weeks, and one sent on the 30th
# and received on the 2nd lands in different months. Repeating each window with
# dates shifted 3 days later moves the boundary, so such pairs fall in the same
# window. Tightest first, so e.g. a same-day pair isn't grouped with other
# same-amount transfers from later in the month.
_SHIFT = datetime.timedelta(days=3)
WINDOWS: list[Window] = [
    ("%Y%m%d", None),  # same day
    ("%Yw%W", None),  # same week (Monday to Sunday)
    ("%Yw%W", _SHIFT),  # same week, shifted: catches Friday -> Monday
    ("%Y%m", None),  # same month
    ("%Y%m", _SHIFT),  # same month, shifted: catches the 29th-31st -> early next month
]


def link_transfers(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Link same-amount transactions in the ``config`` account that cancel out."""
    if not config:
        raise ValueError('link_transfers requires an account, e.g. "Assets:Transfers"')
    return Linker(config, windows=WINDOWS)(entries, options_map)
