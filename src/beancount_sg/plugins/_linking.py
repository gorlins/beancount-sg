"""Link transactions whose postings to a shared account cancel out.

A `Linker` looks at transactions with a posting in a given account (or its
subaccounts) and groups them by a *link key* built from that posting:

    <link_prefix>-<account leaf>[-<date>][-<amount>]

e.g. ``x-Checking-20200115-12.50``. The amount is the absolute value rendered
at the currency's usual precision in the ledger. If a transaction already has
a link that starts with ``<link_prefix>-``, that link is always its key, so
transactions can be grouped by hand.

Matching runs over one or more date *windows* (``strftime`` format and optional
date offset), tightest first. In each window, a group of two or more
not-yet-matched transactions whose linked postings are all in one currency and
sum to zero is matched: each gets the link, and its linked posting is flagged
``*``. Every other posting to the account is flagged ``!``. A transaction with
more than one posting to the account produces an error and is not matched.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, NamedTuple

from beancount.core import account as account_lib
from beancount.core.data import Directive, Meta, Posting, Transaction
from beancount.core.display_context import DisplayFormatter, Precision
from beancount.core.flags import FLAG_OKAY, FLAG_WARNING

Window = tuple[str | None, datetime.timedelta | None]


class LinkError(NamedTuple):
    source: Meta
    message: str
    entry: Directive


class Linker:
    """Groups and links transactions by their postings to ``account``.

    Args:
        account: Postings to this account or its subaccounts are linkable.
        windows: ``(date_format, date_offset)`` pairs to match in, tightest first. A None
            format leaves the date out of the key; the offset shifts dates before formatting.
        link_prefix: Prefix of generated links, and of existing links reused as keys.
        include_amount: Whether the key includes the absolute posting amount.
    """

    def __init__(
        self,
        account: str,
        *,
        windows: Sequence[Window] = (("%Y%m%d", None),),
        link_prefix: str = "x",
        include_amount: bool = True,
    ):
        self.account = account
        self.windows = windows
        self.link_prefix = link_prefix
        self.include_amount = include_amount
        self.is_linkable = account_lib.parent_matcher(account)

    def link_key(
        self, txn: Transaction, posting: Posting, window: Window, formatter: DisplayFormatter
    ) -> str:
        for link in sorted(txn.links or ()):
            if link.startswith(self.link_prefix + "-"):
                return link

        parts = [self.link_prefix, account_lib.leaf(posting.account)]
        date_format, date_offset = window
        if date_format:
            date = txn.date + date_offset if date_offset else txn.date
            parts.append(date.strftime(date_format))
        if self.include_amount:
            number = abs(posting.units.number)
            parts.append(str(formatter.quantize(number, posting.units.currency)))
        return "-".join(parts)

    def __call__(
        self, entries: list[Directive], options_map: dict[str, Any]
    ) -> tuple[list[Directive], list[LinkError]]:
        """Return the entries with matched groups linked and linkable postings flagged."""
        formatter = options_map["dcontext"].build(precision=Precision.MOST_COMMON)
        errors: list[LinkError] = []

        # entry index -> indexes of its postings to the account
        linkable: dict[int, list[int]] = {}
        for i, entry in enumerate(entries):
            if not isinstance(entry, Transaction):
                continue
            indexes = [
                j
                for j, posting in enumerate(entry.postings)
                if self.is_linkable(posting.account) and posting.units is not None
            ]
            if len(indexes) > 1:
                errors.append(
                    LinkError(
                        entry.meta,
                        f"Transaction has {len(indexes)} postings to {self.account}; "
                        "expected at most one to link",
                        entry,
                    )
                )
            if indexes:
                linkable[i] = indexes

        # entry index -> link, for matched transactions
        matched: dict[int, str] = {}
        for window in self.windows:
            groups: dict[str, list[int]] = defaultdict(list)
            for i, indexes in linkable.items():
                if len(indexes) == 1 and i not in matched:
                    posting = entries[i].postings[indexes[0]]
                    groups[self.link_key(entries[i], posting, window, formatter)].append(i)
            for link, members in groups.items():
                units = [entries[i].postings[linkable[i][0]].units for i in members]
                if len(members) < 2 or len({u.currency for u in units}) != 1:
                    continue
                if sum(u.number for u in units) == 0:
                    matched.update(dict.fromkeys(members, link))

        new_entries = list(entries)
        for i, indexes in linkable.items():
            txn = entries[i]
            link = matched.get(i)
            flag = FLAG_OKAY if link else FLAG_WARNING
            postings = list(txn.postings)
            any_changed = False
            for j in indexes:
                if postings[j].flag != flag:
                    postings[j] = postings[j]._replace(flag=flag)
                    any_changed = True
            links = txn.links or frozenset()
            if link and link not in links:
                links = links | {link}
                any_changed = True
            if any_changed:
                new_entries[i] = txn._replace(links=links, postings=postings)
        return new_entries, errors
