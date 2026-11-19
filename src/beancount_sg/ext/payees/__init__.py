"""A Fava report of payees that may be miscategorized or duplicated.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.payees"

The "Payee Review" report looks at the income and expense postings (the
*categories*) of the transactions in the current Fava filter, by payee, and
lists two kinds of likely mistakes:

- **Payees in more than one category**, whose transactions don't all have the
  same categories (a split counts as one choice, so a payee whose transactions
  all split the same way isn't listed). Each with its main category (the one
  with the most transactions) and its others. Payees almost always in one
  category come first: one with 40 transactions in groceries and 1 in dining is
  more likely miscategorized than one spread evenly, like a department store.
- **Similar payee names**, e.g. ``SQ *CORNER COFFEE 0412`` and ``Corner Coffee``:
  groups of payees whose names are at least `SIMILARITY` similar, by rapidfuzz's
  ``WRatio`` (which compares the names' words in several ways, ignoring case and
  punctuation). Each group is centred on its most common name; see
  `similar_names`.

Transactions without a payee are left out of both. A split transaction counts in
each of its categories.

Payees and categories link to the income statement and account pages, filtered
to the payee. When the ``beancount_sg.ext.batch_edit`` extension is enabled,
each finding also links to Batch Edit with a fix filled in: moving a payee's
transactions to its main category, or renaming a group's payees to its most
common name. Batch Edit previews the change before applying it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from beancount.core.account_types import AccountTypes
from beancount.core.amount import Amount
from beancount.core.data import Directive, Transaction
from beancount.parser.options import get_account_types
from fava.context import g
from fava.ext import FavaExtensionBase
from flask import request, url_for
from rapidfuzz import fuzz, utils

from beancount_sg.batch_edit import category_postings

# How similar two payee names must be, out of 100, to be grouped.
SIMILARITY = 90
# The Batch Edit extension's report name, to link to it.
BATCH_EDIT = "BatchEdit"


@dataclass
class Usage:
    """A payee's transactions in one category."""

    account: str
    transactions: int = 0
    totals: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))

    @property
    def total(self) -> list[Amount]:
        return [Amount(number, currency) for currency, number in sorted(self.totals.items())]


@dataclass
class Payee:
    """A payee's categories."""

    name: str
    categories: dict[str, Usage] = field(default_factory=dict)  # by account
    transactions: int = 0
    # Each transaction's set of categories (more than one for a split).
    category_sets: set[frozenset[str]] = field(default_factory=set)

    @property
    def mixed(self) -> bool:
        """Whether its transactions don't all have the same categories.

        A split is one transaction's choice, so a payee whose transactions all
        split the same way isn't mixed.
        """
        return len(self.category_sets) > 1

    @property
    def main(self) -> Usage:
        """The category with the most transactions (the first by name, on a tie)."""
        return min(self.categories.values(), key=lambda usage: (-usage.transactions, usage.account))

    @property
    def others(self) -> list[Usage]:
        """The categories but the main one, by most transactions."""
        main = self.main
        rest = [usage for usage in self.categories.values() if usage is not main]
        return sorted(rest, key=lambda usage: (-usage.transactions, usage.account))

    @property
    def main_share(self) -> Decimal:
        """The main category's share of the payee's category postings, as a percentage."""
        postings = sum(usage.transactions for usage in self.categories.values())
        return Decimal(100 * self.main.transactions) / postings


def payees(entries: Iterable[Directive], account_types: AccountTypes) -> dict[str, Payee]:
    """Each payee's categories, from transactions with a payee, by payee."""
    found: dict[str, Payee] = {}
    for txn in entries:
        if not isinstance(txn, Transaction) or not txn.payee:
            continue
        postings = category_postings(txn, account_types)
        if not postings:
            continue
        payee = found.setdefault(txn.payee, Payee(txn.payee))
        payee.transactions += 1
        accounts = frozenset(posting.account for posting in postings)
        payee.category_sets.add(accounts)
        for account in accounts:
            payee.categories.setdefault(account, Usage(account)).transactions += 1
        for posting in postings:
            usage = payee.categories[posting.account]
            usage.totals[posting.units.currency] += posting.units.number
    return found


def mixed_categories(found: dict[str, Payee]) -> list[Payee]:
    """The payees whose transactions are in different categories, mostly in one first."""
    mixed = [payee for payee in found.values() if payee.mixed]
    return sorted(mixed, key=lambda payee: (-payee.main_share, -payee.transactions, payee.name))


def similar_names(counts: Mapping[str, int], similarity: int = SIMILARITY) -> list[list[str]]:
    """Groups of similar names: each a name, then the others similar to it.

    Names are taken in order of ``counts`` (most first): each that's not yet in a
    group starts one, with the remaining names at least ``similarity`` similar to
    it (out of 100, by rapidfuzz's ``WRatio``, ignoring case and punctuation),
    most first. So a group is centred on its most common name, rather than
    chaining names similar to each other into one large group.

    Only names that share a word (3+ letters or digits, not just digits) are
    compared, which keeps this fast for thousands of payees; names that share
    none, e.g. ``WholeFoods`` and ``Whole Foods``, aren't grouped.
    """
    order = sorted(counts, key=lambda name: (-counts[name], name))
    rank = {name: i for i, name in enumerate(order)}
    normalized = {name: utils.default_process(name) for name in order}
    by_word: dict[str, set[str]] = defaultdict(set)
    for name in order:
        for word in _words(normalized[name]):
            by_word[word].add(name)
    grouped: set[str] = set()
    groups: list[list[str]] = []
    for name in order:
        if name in grouped:
            continue
        candidates = {other for word in _words(normalized[name]) for other in by_word[word]}
        similar = [
            other
            for other in candidates - grouped - {name}
            if fuzz.WRatio(normalized[name], normalized[other], score_cutoff=similarity)
        ]
        if similar:
            group = [name, *sorted(similar, key=rank.__getitem__)]
            grouped.update(group)
            groups.append(group)
    return groups


def _words(normalized: str) -> set[str]:
    """A normalized name's words worth comparing on: 3+ characters, not just digits."""
    return {word for word in normalized.split() if len(word) >= 3 and not word.isdigit()}


def payee_pattern(names: Iterable[str]) -> str:
    """A regex matching exactly these payees (case-insensitively, as Fava and Batch Edit do)."""
    return "^(?:" + "|".join(re.escape(name) for name in sorted(names)) + ")$"


def payee_filter(names: Iterable[str]) -> str:
    """A Fava filter for transactions with one of these payees."""
    # \x22 is a quote, which would otherwise end the filter's string.
    pattern = payee_pattern(names).replace('"', r"\x22")
    return f'payee:"{pattern}"'


@dataclass(frozen=True)
class SimilarGroup:
    """A group of similar payee names."""

    payees: list[Payee]  # by most transactions

    @property
    def names(self) -> list[str]:
        return [payee.name for payee in self.payees]

    @property
    def most_common(self) -> str:
        return self.payees[0].name

    @property
    def transactions(self) -> int:
        return sum(payee.transactions for payee in self.payees)


class PayeeReview(FavaExtensionBase):
    """Fava report of payees that may be miscategorized or duplicated."""

    report_title = "Payee Review"

    def _payees(self) -> dict[str, Payee]:
        return payees(g.filtered.entries, get_account_types(self.ledger.options))

    def review(self) -> tuple[list[Payee], list[SimilarGroup], int]:
        """Payees in several categories, groups of similar payees, and the number of payees."""
        found = self._payees()
        groups = [
            SimilarGroup(
                sorted(
                    (found[name] for name in names),
                    key=lambda payee: (-payee.transactions, payee.name),
                )
            )
            for names in similar_names({name: payee.transactions for name, payee in found.items()})
        ]
        groups.sort(key=lambda group: (-group.transactions, group.most_common))
        return mixed_categories(found), groups, len(found)

    def payee_url(self, names: Iterable[str]) -> str:
        """The income statement, filtered to these payees."""
        return url_for(
            "report", report_name="income_statement", filter=_with_current(payee_filter(names))
        )

    def account_url(self, account: str, names: Iterable[str]) -> str:
        """An account's page, filtered to these payees."""
        return url_for("account", name=account, filter=_with_current(payee_filter(names)))

    def batch_edit_url(self, names: Iterable[str], **fields: str) -> str | None:
        """Batch Edit, searching for these payees with these fields, if it's enabled."""
        if not self.ledger.extensions.get_extension(BATCH_EDIT):
            return None
        return url_for(
            "extension_report",
            extension_name=BATCH_EDIT,
            payee_regex=payee_pattern(names),
            **fields,
        )


def _with_current(payee_filter_str: str) -> str:
    """A filter for some payees, within the page's current filter, if any."""
    current = request.args.get("filter")
    return f"({current}) ({payee_filter_str})" if current else payee_filter_str
