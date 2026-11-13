"""Link bills to their payments.

Transactions posting to the configured account (or its subaccounts) in the
same month are linked when those postings cancel out, e.g. a bill accrued to
``Liabilities:Bills:Electric`` and the payment that clears it. Amounts are not
part of the key, so a month's bill and payment are matched even if paid in
parts. See `beancount_sg.linking.Linker` for details.

Usage::

    plugin "beancount_sg.plugins.link_bills" "Liabilities:Bills"
"""

from __future__ import annotations

from typing import Any

from beancount.core.data import Directive

from beancount_sg.linking import Linker

__plugins__ = ("link_bills",)


def link_bills(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Link each month's transactions in the ``config`` account that cancel out."""
    if not config:
        raise ValueError('link_bills requires an account, e.g. "Liabilities:Bills"')
    linker = Linker(config, date_format="%Y%m", include_amount=False)
    return linker(entries), []
