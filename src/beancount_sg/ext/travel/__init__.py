"""A Fava report of travel spending, by trip and by expense category.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.travel"

Travel spending is the expense postings of transactions tagged ``#travel``, in
the current Fava filter (refunds count negatively). A transaction's *trip* is its
trip tag, e.g. ``#miami-2025``, as `beancount_sg.plugins.tag_travel` adds. The
trips are the tags that occur on ``#travel`` transactions and on no other
transactions, anywhere in the ledger: a tag also used without ``#travel``, such
as ``#recurring``, isn't a trip. Travel spending without a trip tag is counted
as "no trip", and called out above the report.

A travel transaction should have only one trip tag. One with several counts
towards the first, alphabetically, and is listed in a warning on the page, so
it can be fixed. And a trip tag used once without ``#travel`` stops being a trip,
so its spending shows as "no trip".

The report has hierarchy charts of the spending, by trip then expense account
("By trip"), and by expense account then trip ("By category"); a bar chart of
the spending in each of Fava's intervals (e.g. monthly, as chosen in the chart's
interval menu), stacked by trip ("Over time"); and a table of
trips with their dates, number of transactions and total. Every link, in the
table or the charts, opens a Fava page filtered by the trip's tag (or, for
spending without a trip, ``#travel`` without any trip tag): a trip opens the
income statement, and an expense account opens that account's page.

Fava's charts link every node, and every bar segment, to an account page, so the
page's script (``Travel.js``) points them at these filtered pages instead. A bar
group links to its interval, as in Fava.
"""

from __future__ import annotations

import bisect
import datetime
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core.account_types import get_account_type
from beancount.core.amount import Amount
from beancount.core.data import Directive, Posting, Transaction
from beancount.parser.options import get_account_types
from fava.beans.funcs import hash_entry
from fava.context import g
from fava.core.charts import DateAndBalanceWithBudget
from fava.core.inventory import SimpleCounterInventory
from fava.core.tree import SerialisedTreeNode
from fava.ext import FavaExtensionBase
from fava.internal_api import BarChart, HierarchyChart
from fava.util.date import DateRange
from flask import request, url_for

from beancount_sg.plugins.tag_travel import TAG

# The chart node and table label for travel spending without a trip tag.
NO_TRIP = "no trip"
# The "By trip" chart's root node.
TRIPS_ROOT = "All trips"


@dataclass
class Trip:
    """A trip's travel transactions: their dates, count and total spending."""

    tag: str | None  # None for travel spending without a trip tag
    first: datetime.date
    last: datetime.date
    transactions: int = 0
    totals: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))

    @property
    def label(self) -> str:
        return f"#{self.tag}" if self.tag else NO_TRIP

    @property
    def total(self) -> list[Amount]:
        return [Amount(number, currency) for currency, number in sorted(self.totals.items())]


@dataclass(frozen=True)
class Spending:
    """Travel spending on one trip, expense account and currency."""

    trip: str | None
    account: str
    amount: Amount


def ledger_trips(entries: Iterable[Directive]) -> frozenset[str]:
    """The trips: tags that occur on ``#travel`` transactions, and only on them.

    A tag also used on a transaction without ``#travel``, e.g. ``#recurring``,
    isn't a trip.
    """
    on_travel: set[str] = set()
    elsewhere: set[str] = set()
    for txn in entries:
        if isinstance(txn, Transaction):
            (on_travel if TAG in txn.tags else elsewhere).update(txn.tags)
    return frozenset(on_travel - elsewhere - {TAG})


def trip_tags(txn: Transaction, trips: Collection[str]) -> list[str]:
    """A transaction's tags that are trips, sorted."""
    return sorted(tag for tag in txn.tags if tag in trips)


@dataclass(frozen=True)
class TravelSpending:
    """Travel spending per trip, account and currency, and its trips."""

    rows: list[Spending]
    trips: list[Trip]  # by first date
    # Travel transactions with several trip tags, counted towards the first.
    several_trips: list[Transaction]


def travel_spending(
    entries: Iterable[Directive], expenses: str, trips: Collection[str]
) -> TravelSpending:
    """Travel spending per trip, account and currency, and the trips.

    Args:
        entries: The entries to count.
        expenses: The expenses root account's name.
        trips: The trip tags, from `ledger_trips`.
    """
    spending: dict[tuple[str | None, str, str], Decimal] = defaultdict(Decimal)
    by_trip: dict[str | None, Trip] = {}
    several_trips: list[Transaction] = []
    for txn in entries:
        if not isinstance(txn, Transaction):
            continue
        postings = travel_postings(txn, expenses)
        if not postings:
            continue
        tags = trip_tags(txn, trips)
        if len(tags) > 1:
            several_trips.append(txn)
        tag = tags[0] if tags else None
        trip = by_trip.setdefault(tag, Trip(tag, txn.date, txn.date))
        trip.first = min(trip.first, txn.date)
        trip.last = max(trip.last, txn.date)
        trip.transactions += 1
        for posting in postings:
            spending[(tag, posting.account, posting.units.currency)] += posting.units.number
            trip.totals[posting.units.currency] += posting.units.number
    rows = [
        Spending(tag, account, Amount(number, currency))
        for (tag, account, currency), number in sorted(
            spending.items(), key=lambda item: (item[0][0] or "", item[0][1], item[0][2])
        )
    ]
    return TravelSpending(
        rows, sorted(by_trip.values(), key=lambda trip: (trip.first, trip.tag or "")), several_trips
    )


def travel_postings(txn: Transaction, expenses: str) -> list[Posting]:
    """A transaction's travel spending: its expense postings, if it's tagged ``#travel``."""
    if TAG not in txn.tags:
        return []
    return [posting for posting in txn.postings if get_account_type(posting.account) == expenses]


def spending_over_time(
    entries: Iterable[Directive],
    expenses: str,
    trips: Collection[str],
    ranges: Sequence[DateRange],
) -> list[DateAndBalanceWithBudget]:
    """Travel spending in each date range, in total and per trip, for a bar chart.

    Like Fava's own bar charts, each range is dated by its last day. The trips are
    keyed by their tag, or `NO_TRIP`.
    """
    begins = [date_range.begin for date_range in ranges]
    by_range: list[dict[str, dict[str, Decimal]]] = [{} for _ in ranges]
    for txn in entries:
        if not isinstance(txn, Transaction):
            continue
        index = bisect.bisect_right(begins, txn.date) - 1
        if index < 0 or txn.date >= ranges[index].end:
            continue
        tags = trip_tags(txn, trips)
        by_trip = by_range[index].setdefault(tags[0] if tags else NO_TRIP, defaultdict(Decimal))
        for posting in travel_postings(txn, expenses):
            by_trip[posting.units.currency] += posting.units.number
    data = []
    for date_range, by_trip in zip(ranges, by_range, strict=True):
        total = SimpleCounterInventory()
        for balance in by_trip.values():
            for currency, number in balance.items():
                total[currency] = total.get(currency, Decimal(0)) + number
        account_balances = {
            trip: SimpleCounterInventory(balance) for trip, balance in by_trip.items() if balance
        }
        data.append(DateAndBalanceWithBudget(date_range.end_inclusive, total, account_balances, {}))
    return data


def trip_filter(tag: str | None, trip_tags: Iterable[str]) -> str:
    """A Fava filter for a trip's travel transactions.

    Without a trip, ``#travel`` without any of the trip tags.
    """
    if tag:
        return f"#{TAG} #{tag}"
    return " ".join([f"#{TAG}", *(f"-#{other}" for other in sorted(trip_tags))])


class Travel(FavaExtensionBase):
    """Fava report of travel spending by trip and expense category."""

    report_title = "Travel"
    has_js_module = True

    def _expenses(self) -> str:
        return get_account_types(self.ledger.options).expenses

    def report(self) -> TravelReport:
        """The travel spending in the current Fava filter."""
        # Which tags are trips depends on the whole ledger, whatever the filter.
        trips = ledger_trips(self.ledger.all_entries)
        spending = travel_spending(g.filtered.entries, self._expenses(), trips)
        return TravelReport(
            spending.rows, spending.trips, spending.several_trips, self._expenses(), trips
        )

    def charts(self, report: TravelReport) -> list[HierarchyChart | BarChart]:
        """The report's hierarchy charts, and its spending over Fava's intervals."""
        # Like Fava's bar charts: its interval, and at most its last 100 periods.
        ranges = g.filtered.interval_ranges(g.interval)[-100:]
        over_time = spending_over_time(
            g.filtered.entries, self._expenses(), report.ledger_trips, ranges
        )
        return [*report.charts(), BarChart(f"Over time ({g.interval.label})", over_time)]


@dataclass(frozen=True)
class TravelReport:
    """Travel spending, its trips, and their links and charts."""

    rows: list[Spending]
    trips: list[Trip]
    several_trips: list[Transaction]
    expenses: str
    ledger_trips: frozenset[str]

    @property
    def trip_tags(self) -> list[str]:
        return sorted(trip.tag for trip in self.trips if trip.tag)

    @property
    def tagged(self) -> list[Trip]:
        """The trips with a trip tag."""
        return [trip for trip in self.trips if trip.tag]

    @property
    def untagged(self) -> Trip | None:
        """Travel spending without a trip tag, if any."""
        return next((trip for trip in self.trips if not trip.tag), None)

    @property
    def total(self) -> list[Amount]:
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for trip in self.trips:
            for currency, number in trip.totals.items():
                totals[currency] += number
        return [Amount(number, currency) for currency, number in sorted(totals.items())]

    @staticmethod
    def entry_hash(txn: Transaction) -> str:
        """Fava's id for a transaction, to link to it."""
        return hash_entry(txn)

    def transaction_trips(self, txn: Transaction) -> list[str]:
        """A transaction's trip tags."""
        return trip_tags(txn, self.ledger_trips)

    def trip_filter(self, tag: str | None) -> str:
        """The Fava filter for a trip's travel transactions (or those without a trip)."""
        return trip_filter(tag, self.trip_tags)

    def trip_url(self, tag: str | None) -> str:
        """The income statement, filtered to a trip's travel transactions."""
        return report_url(self.trip_filter(tag))

    def account_url(self, account: str, travel_filter: str) -> str:
        """An account's page, filtered to some travel transactions."""
        return url_for("account", name=account, filter=_with_current_filter(travel_filter))

    def charts(self) -> list[HierarchyChart]:
        """Hierarchy charts by trip then account, and by account then trip."""
        by_trip, _ = self._by_trip()
        by_category, _ = self._by_category()
        return [HierarchyChart("By trip", by_trip), HierarchyChart("By category", by_category)]

    def chart_links(self) -> dict[str, str]:
        """Each chart node's name, and the filtered page it should link to."""
        _, trip_links = self._by_trip()
        _, category_links = self._by_category()
        # The "Over time" chart's bars are stacked by trip, keyed by tag.
        bar_links = {trip.tag or NO_TRIP: self.trip_url(trip.tag) for trip in self.trips}
        return {**trip_links, **category_links, **bar_links}

    def _by_trip(self) -> tuple[SerialisedTreeNode, dict[str, str]]:
        amounts: dict[tuple[str, ...], dict[str, Decimal]] = {}
        links = {TRIPS_ROOT: report_url(f"#{TAG}")}
        for row in self.rows:
            trip = row.trip or NO_TRIP
            links[f"{TRIPS_ROOT}:{trip}"] = self.trip_url(row.trip)
            # The account's components below the expenses root, under the trip; a
            # posting to the root itself is shown under the root's name.
            parts = account_lib.split(row.account)[1:]
            accounts = [
                account_lib.join(self.expenses, *parts[:depth])
                for depth in range(1, len(parts) + 1)
            ]
            if not parts:
                parts, accounts = [self.expenses], [self.expenses]
            for depth, account in enumerate(accounts, start=1):
                links[account_lib.join(TRIPS_ROOT, trip, *parts[:depth])] = self.account_url(
                    account, self.trip_filter(row.trip)
                )
            path = (TRIPS_ROOT, trip, *parts)
            _add(amounts, path, row.amount)
        return _tree(amounts, (TRIPS_ROOT,)), links

    def _by_category(self) -> tuple[SerialisedTreeNode, dict[str, str]]:
        amounts: dict[tuple[str, ...], dict[str, Decimal]] = {}
        links: dict[str, str] = {}
        for row in self.rows:
            parts = account_lib.split(row.account)
            for depth in range(1, len(parts) + 1):
                account = account_lib.join(*parts[:depth])
                links[account] = self.account_url(account, f"#{TAG}")
            trip = row.trip or NO_TRIP
            links[account_lib.join(row.account, trip)] = self.account_url(
                row.account, self.trip_filter(row.trip)
            )
            _add(amounts, (*parts, trip), row.amount)
        return _tree(amounts, (self.expenses,)), links


def _with_current_filter(travel_filter: str) -> str:
    """A filter for travel transactions, within the page's current filter, if any."""
    current = request.args.get("filter")
    return f"({current}) ({travel_filter})" if current else travel_filter


def report_url(travel_filter: str) -> str:
    """The income statement, filtered to some travel transactions."""
    return url_for(
        "report", report_name="income_statement", filter=_with_current_filter(travel_filter)
    )


def _add(
    amounts: dict[tuple[str, ...], dict[str, Decimal]], path: tuple[str, ...], amount: Amount
) -> None:
    by_currency = amounts.setdefault(path, defaultdict(Decimal))
    by_currency[amount.currency] += amount.number


def _tree(
    amounts: dict[tuple[str, ...], dict[str, Decimal]], root: tuple[str, ...]
) -> SerialisedTreeNode:
    """A chart tree of amounts at account-like paths, from the root path."""
    children: dict[tuple[str, ...], set[tuple[str, ...]]] = defaultdict(set)
    for path in amounts:
        for depth in range(len(root), len(path)):
            children[path[:depth]].add(path[: depth + 1])
    return _serialise(root, amounts, children)


def _serialise(
    path: tuple[str, ...],
    amounts: dict[tuple[str, ...], dict[str, Decimal]],
    children: dict[tuple[str, ...], set[tuple[str, ...]]],
) -> SerialisedTreeNode:
    nodes = [_serialise(child, amounts, children) for child in sorted(children[path])]
    balance = SimpleCounterInventory(amounts.get(path, {}))
    total = SimpleCounterInventory(balance)
    for node in nodes:
        for currency, number in node.balance_children.items():
            total[currency] = total.get(currency, Decimal(0)) + number
    return SerialisedTreeNode(
        account_lib.join(*path), balance, total, nodes, has_txns=bool(balance)
    )
