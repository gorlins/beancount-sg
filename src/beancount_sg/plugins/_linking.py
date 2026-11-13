"""Link transactions whose postings to a shared account cancel out.

A `Linker` looks at transactions with a posting in a given account (or its
subaccounts) and groups them by a *link key* built from that posting:

    <link_prefix>-<account leaf>[-<date>][-<amount>]

e.g. ``x-Checking-20200115-12.50``. The amount is the absolute value rendered
at the currency's usual precision in the ledger.

By default the account part is only the last component, which keeps links
short and readable. The weakness is that subaccounts with the same leaf name,
e.g. ``Liabilities:Bills:Home:Electric`` and ``Liabilities:Bills:Office:Electric``,
share keys, so their transactions can be matched against each other. Pass a
different ``account_key`` function to tell them apart.

If a transaction already has a link that starts with ``<link_prefix>-``, that
link is always its key, so manual or pre-existing groupings are preserved.
Having more than one such link on a transaction isn't supported: whichever is
found first is used.

Matching runs over one or more date *windows* (``strftime`` format and optional
date offset), in order. In each window, a group of two or more not-yet-matched
transactions whose linked postings are all in one currency and sum to zero is
matched: each gets the link, and its linked posting is flagged ``*``. A
transaction matched in one window isn't considered in later ones. Every other
posting to the account is flagged ``!``. Postings to the account are flagged
whatever their current flag; transaction flags are never changed (use
``beancount_sg.plugins.flag_from_postings`` to roll posting flags up). A
transaction's postings to a single linked account are treated as one: they are
summed for the key and for matching, and all of them are flagged. A transaction
with postings to more than one linked account (e.g. both ``Bills:Electric`` and
``Bills:Water``), or to one account in several currencies, produces an error and
is not matched.

Strategy
--------

Rather than comparing each transaction against every other one within a
sliding date range (a convolution over the window, O(n²) in the worst case), the
linker computes one hashable key per transaction and buckets transactions by
key. Each window is a single O(n) pass: compute keys, group them in a dict, and
check each group's sum. Everything that should match is found by key lookup, so
the cost doesn't grow with the size of the date range or with ledger density.

The trade-off is that keys are *calendar* buckets, not sliding ranges: a Friday
and the following Monday fall in different weeks, however close they are. That
is what multiple windows are for. Repeating a window with its dates shifted
moves the bucket boundaries, so pairs split by one window's boundary land
together in the shifted one.

A key's whole group must cancel to match. The key is the definition of "these
belong together". If a group doesn't sum to zero (say two -100s and one +100 in
the same week), the linker doesn't guess which subset is the real pair. The
group stays ``!`` for a human to resolve, e.g. by adding a manual link.

Order windows from narrowest to widest. Because a group only matches if *all*
of its members cancel, a wide window can lump together transactions that
narrower windows would pair off separately (two transfers in a month, say), or
fail to match any of them. Windows of the same width, such as one period with
different offsets, can go in any order: they cover different boundaries, and
when a pair falls in more than one of them, the earlier window decides its
link.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from beancount.core import account as account_lib
from beancount.core.amount import Amount
from beancount.core.data import BeancountError, Directive, Meta, Transaction
from beancount.core.display_context import DisplayFormatter, Precision
from beancount.core.flags import FLAG_OKAY, FLAG_WARNING

# (strftime format for the date part of the key, or None to omit it; offset added to
# each transaction's date before formatting, or None)
Window = tuple[str | None, datetime.timedelta | None]


class LinkError(NamedTuple):
    """Conforms to `beancount.core.data.BeancountError`, a Protocol that can't be subclassed.

    Beancount's own errors are NamedTuples with these fields too.
    """

    source: Meta
    message: str
    entry: Directive


class Linker:
    """Groups and links transactions by their postings to ``account``.

    Args:
        account: Postings to this account or its subaccounts are linkable.
        windows: ``(date_format, date_offset)`` pairs to match in, narrowest first (see the
            module docs). A None format leaves the date out of the key. The offset is added
            to each date before formatting, so a positive offset moves the bucket
            boundaries earlier (e.g. +3 days puts Friday into the following week).
        link_prefix: Prefix of generated links, and of existing links reused as keys.
        include_amount: Whether the key includes the absolute posting amount.
        account_key: Maps a posting's account to the account part of the key. Defaults
            to its leaf (e.g. ``Electric``); pass another function to distinguish
            subaccounts that share a leaf name (see the module docs). The result must
            only use characters valid in a link: letters, digits and ``-_/.``.
    """

    def __init__(
        self,
        account: str,
        *,
        windows: Sequence[Window] = (("%Y%m%d", None),),
        link_prefix: str = "x",
        include_amount: bool = True,
        account_key: Callable[[str], str] = account_lib.leaf,
    ):
        self.account = account
        self.windows = windows
        self.link_prefix = link_prefix
        self.include_amount = include_amount
        self.account_key = account_key
        # Matches the account and its subaccounts, on component boundaries.
        self.is_linkable = account_lib.parent_matcher(account)

    def link_key(
        self,
        txn: Transaction,
        account: str,
        units: Amount,
        window: Window,
        formatter: DisplayFormatter,
    ) -> str:
        """The key grouping ``txn`` in ``window``, via its postings to ``account``.

        ``units`` is the sum of those postings. ``formatter`` renders amounts at each
        currency's usual precision, so that e.g. ``1.1`` and ``1.10`` USD produce the
        same key.
        """
        # A link with our prefix already on the transaction, whether added by hand or by
        # an earlier tool, is kept as its key, so those groupings are preserved.
        for link in txn.links or ():
            if link.startswith(self.link_prefix + "-"):
                return link

        parts = [self.link_prefix, self.account_key(account)]
        date_format, date_offset = window
        if date_format:
            date = txn.date + date_offset if date_offset else txn.date
            parts.append(date.strftime(date_format))
        if self.include_amount:
            parts.append(str(formatter.quantize(abs(units.number), units.currency)))
        return "-".join(parts)

    def __call__(
        self, entries: list[Directive], options_map: dict[str, Any]
    ) -> tuple[list[Directive], list[BeancountError]]:
        """Return the entries with matched groups linked and linkable postings flagged."""
        formatter = options_map["dcontext"].build(precision=Precision.MOST_COMMON)
        errors: list[BeancountError] = []

        # Find each transaction's postings to the account. Plugins run after Beancount
        # fills in missing amounts, so every posting has units.
        # entry index -> indexes of its postings to the account (all get flagged)
        linkable: dict[int, list[int]] = {}
        # entry index -> (account, summed units), for transactions that can be matched
        totals: dict[int, tuple[str, Amount]] = {}
        for i, entry in enumerate(entries):
            if not isinstance(entry, Transaction):
                continue
            indexes = [
                j for j, posting in enumerate(entry.postings) if self.is_linkable(posting.account)
            ]
            if not indexes:
                continue
            linkable[i] = indexes

            postings = [entry.postings[j] for j in indexes]
            accounts = {posting.account for posting in postings}
            currencies = {posting.units.currency for posting in postings}
            # Postings to one account are summed and linked as one. Postings to several
            # accounts, or in several currencies, can't be: report an error and leave the
            # transaction out of matching, so its postings get flagged !.
            if len(accounts) > 1:
                problem = f"postings to {len(accounts)} accounts under {self.account}"
            elif len(currencies) > 1:
                problem = f"postings to {accounts.pop()} in {len(currencies)} currencies"
            else:
                number = sum(posting.units.number for posting in postings)
                totals[i] = (accounts.pop(), Amount(number, currencies.pop()))
                continue
            errors.append(LinkError(entry.meta, f"Transaction has {problem}; can't link it", entry))

        # Match window by window: entry index -> link, for matched transactions.
        matched: dict[int, str] = {}
        for window in self.windows:
            # Group the transactions not matched yet by their key in this window.
            groups: dict[str, list[int]] = defaultdict(list)
            for i, (account, units) in totals.items():
                if i not in matched:
                    key = self.link_key(entries[i], account, units, window, formatter)
                    groups[key].append(i)
            # A group of two or more in one currency that sums to zero is a match!
            for link, members in groups.items():
                units = [totals[i][1] for i in members]
                if len(members) < 2 or len({u.currency for u in units}) != 1:
                    continue
                if sum(u.number for u in units) == 0:
                    matched.update(dict.fromkeys(members, link))

        # Apply the results: matched transactions get the link and * on their postings to
        # the account; every other posting to the account gets !.
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
            # Only rebuild transactions that actually change.
            if any_changed:
                new_entries[i] = txn._replace(links=links, postings=postings)
        return new_entries, errors
