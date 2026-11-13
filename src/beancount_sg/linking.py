"""Link transactions whose postings to a shared account cancel out.

A `Linker` looks at transactions with a posting in a given account (or its
subaccounts) and groups them by a *link key* built from that posting:

    <link_prefix>-<last account component>[-<date>][-<amount>]

e.g. ``x-Checking-20200115-12.5``. If a transaction already has a link that
starts with ``<link_prefix>-``, that link is used as its key instead, so
transactions can be grouped by hand. A group of two or more transactions whose
linked postings are all in one currency and sum to zero is matched: each
transaction gets the link, and its linked posting is flagged ``*``. Everything
else is returned unchanged.

Only the first posting in a transaction that is in the linked account is used.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass

from beancount.core.data import Directive, Posting, Transaction
from beancount.core.flags import FLAG_OKAY


@dataclass(frozen=True)
class Linker:
    """Groups and links transactions by their postings to ``account``.

    Attributes:
        account: Postings to this account or its subaccounts are linkable.
        link_prefix: Prefix of generated links, and of existing links reused as keys.
        date_format: ``strftime`` format for the date part of the key, or None to omit it.
        date_offset: Shifts the transaction date before formatting it.
        include_amount: Whether the key includes the absolute posting amount.
    """

    account: str
    link_prefix: str = "x"
    date_format: str | None = "%Y%m%d"
    date_offset: datetime.timedelta | None = None
    include_amount: bool = True

    def is_linkable(self, posting: Posting) -> bool:
        return posting.account == self.account or posting.account.startswith(self.account + ":")

    def link_key(self, txn: Transaction, posting: Posting) -> str:
        for link in sorted(txn.links or ()):
            if link.startswith(self.link_prefix + "-"):
                return link

        parts = [self.link_prefix, posting.account.rsplit(":", 1)[-1]]
        if self.date_format:
            date = txn.date + self.date_offset if self.date_offset else txn.date
            parts.append(date.strftime(self.date_format))
        if self.include_amount:
            # Normalized so that e.g. 12.5 and 12.50 produce the same key.
            parts.append(f"{abs(posting.units.number).normalize():f}")
        return "-".join(parts)

    def __call__(self, entries: list[Directive]) -> list[Directive]:
        """Return the entries, with each matched group of transactions linked."""
        # link key -> [(entry index, linked posting index)]
        groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, entry in enumerate(entries):
            if not isinstance(entry, Transaction):
                continue
            for j, posting in enumerate(entry.postings):
                if self.is_linkable(posting) and posting.units is not None:
                    groups[self.link_key(entry, posting)].append((i, j))
                    break

        new_entries = list(entries)
        for link, members in groups.items():
            units = [entries[i].postings[j].units for i, j in members]
            if len(members) < 2 or len({u.currency for u in units}) != 1:
                continue
            if sum(u.number for u in units) != 0:
                continue
            for i, j in members:
                txn = entries[i]
                if link in (txn.links or ()) and txn.postings[j].flag == FLAG_OKAY:
                    continue
                postings = list(txn.postings)
                postings[j] = postings[j]._replace(flag=FLAG_OKAY)
                new_entries[i] = txn._replace(
                    links=(txn.links or frozenset()) | {link}, postings=postings
                )
        return new_entries
