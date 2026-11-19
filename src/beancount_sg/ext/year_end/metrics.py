"""The Year in Review's calculations: net worth groups and yearly summaries.

Net worth is assets minus liabilities (what's owed), in groups:

- **Cash**: assets with the ``cash`` cash-flow role (see
  `beancount_sg.cash_flow_roles`).
- **Investments**: other assets, unless they're property.
- **Property**: assets you live in or use rather than invest, e.g. a home. An
  asset is property if its ``open`` directive (or a parent's) says
  ``investable: FALSE``, or else if a liability is opened under the matching
  path, e.g. ``Assets:Home`` and ``Liabilities:Home:Mortgage`` (a secured loan).
  ``investable: TRUE`` makes it an investment, whatever liabilities match it.
- **Debt**: loans, i.e. liabilities with the ``financing`` role, except credit
  cards: those without a declared role and named with Card.
- **Other**: the remaining liabilities, e.g. credit card balances.

Investable assets are cash and investments: what spending could be drawn from.

All values are in one currency: holdings at their market value on the date (or
at cost, if they have no price yet), and income and spending at their value on
each transaction's date. Amounts that can't be converted, for lack of prices,
are left out and their currencies reported.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core import convert, prices
from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Directive, Open, Posting, Transaction
from beancount.core.inventory import Inventory

from beancount_sg.cash_flow_roles import CASH, FINANCING, Role

INVESTABLE_KEY = "investable"
# Names of liabilities that are credit cards, rather than loans, by default.
CARD_NAMES = re.compile(r"card", re.IGNORECASE)
INVESTMENTS, PROPERTY, DEBT, OTHER = "investments", "property", "debt", "other"
GROUPS = (CASH, INVESTMENTS, PROPERTY, DEBT, OTHER)
MAX_YEARS = 5
ONE_DAY = datetime.timedelta(days=1)


@dataclass(frozen=True)
class Classification:
    """An asset or liability's net worth group, and why."""

    group: str
    reason: str


def classify(
    opens: Iterable[Open], roles: Mapping[str, Role], account_types: AccountTypes
) -> dict[str, Classification]:
    """Each asset and liability's net worth group."""
    opens = list(opens)
    investable = {
        entry.account: entry.meta[INVESTABLE_KEY] for entry in opens if INVESTABLE_KEY in entry.meta
    }
    liabilities = [
        entry.account
        for entry in opens
        if get_account_type(entry.account) == account_types.liabilities
    ]
    found = {}
    for entry in opens:
        account = entry.account
        root = get_account_type(account)
        role = roles[account]
        if root == account_types.assets:
            found[account] = _asset(account, role, investable, liabilities)
        elif root == account_types.liabilities:
            found[account] = _liability(account, role)
    return found


def _asset(
    account: str, role: Role, investable: Mapping[str, object], liabilities: list[str]
) -> Classification:
    if role.role == CASH:
        return Classification(CASH, _role_reason(role))
    # Its own investable metadata, or its nearest parent's.
    for name in account_lib.parents(account):
        if name in investable:
            group = INVESTMENTS if investable[name] else PROPERTY
            return Classification(group, f"{INVESTABLE_KEY}: {investable[name]} on {name}")
    # A liability under the matching path, e.g. Liabilities:Home:Mortgage for Assets:Home.
    path = account_lib.split(account)[1:]
    for liability in liabilities:
        if path and account_lib.split(liability)[1 : len(path) + 1] == path:
            return Classification(PROPERTY, f"secures {liability}")
    return Classification(INVESTMENTS, _role_reason(role))


def _liability(account: str, role: Role) -> Classification:
    if role.role != FINANCING:
        return Classification(OTHER, _role_reason(role))
    if not role.declared and CARD_NAMES.search(account):
        return Classification(OTHER, "a credit card, by its name")
    return Classification(DEBT, _role_reason(role))


def _role_reason(role: Role) -> str:
    if role.declared:
        return f"{role.role}, declared on {role.declared_by}"
    return f"{role.role}, by default"


@dataclass
class Debt:
    """A loan's balance over a year: owed amounts are positive."""

    account: str
    start: Decimal = Decimal(0)
    borrowed: Decimal = Decimal(0)
    paid: Decimal = Decimal(0)
    end: Decimal = Decimal(0)


@dataclass
class YearSummary:
    """A year's metrics, in one currency.

    ``end`` is the day after the last day counted: the next January 1st, or for
    the current year, tomorrow (so the year is year-to-date).
    """

    year: int
    end: datetime.date
    # Net worth by group, at the start and end of the year. Liabilities are negative.
    holdings_start: dict[str, Decimal] = field(default_factory=dict)
    holdings: dict[str, Decimal] = field(default_factory=dict)
    income: Decimal = Decimal(0)
    expenses: Decimal = Decimal(0)
    expenses_by_category: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    debts: list[Debt] = field(default_factory=list)

    @property
    def start(self) -> datetime.date:
        return datetime.date(self.year, 1, 1)

    @property
    def complete(self) -> bool:
        """Whether the whole year is counted, rather than year-to-date."""
        return self.end == datetime.date(self.year + 1, 1, 1)

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def net_worth_start(self) -> Decimal:
        return sum(self.holdings_start.values(), Decimal(0))

    @property
    def net_worth(self) -> Decimal:
        """Assets minus liabilities at the end of the year."""
        return sum(self.holdings.values(), Decimal(0))

    @property
    def net_worth_change(self) -> Decimal:
        return self.net_worth - self.net_worth_start

    @property
    def investable_start(self) -> Decimal:
        return _investable(self.holdings_start)

    @property
    def investable(self) -> Decimal:
        """Cash and investments at the end of the year."""
        return _investable(self.holdings)

    @property
    def savings(self) -> Decimal:
        """Income minus expenses."""
        return self.income - self.expenses

    @property
    def savings_rate(self) -> Decimal | None:
        """Savings as a percentage of income."""
        return 100 * self.savings / self.income if self.income > 0 else None

    @property
    def annual_expenses(self) -> Decimal:
        """Expenses, scaled to a whole year when the year is year-to-date."""
        return self.expenses if self.complete else self.expenses * 365 / self.days

    @property
    def spending_rate(self) -> Decimal | None:
        """Annual expenses as a percentage of net worth at the start of the year."""
        return _percentage(self.annual_expenses, self.net_worth_start)

    @property
    def withdrawal_rate(self) -> Decimal | None:
        """Annual expenses as a percentage of investable assets at the start of the year.

        Like a withdrawal rate in retirement: what share of the cash and
        investments you could draw on a year's spending would take.
        """
        return _percentage(self.annual_expenses, self.investable_start)

    @property
    def months_of_cash(self) -> Decimal | None:
        """Cash at the end of the year, in months of annual expenses."""
        if self.annual_expenses <= 0:
            return None
        return 12 * self.holdings.get(CASH, Decimal(0)) / self.annual_expenses

    @property
    def top_categories(self) -> list[tuple[str, Decimal]]:
        return sorted(self.expenses_by_category.items(), key=lambda item: -item[1])


def _investable(holdings: Mapping[str, Decimal]) -> Decimal:
    return holdings.get(CASH, Decimal(0)) + holdings.get(INVESTMENTS, Decimal(0))


def _percentage(part: Decimal, whole: Decimal) -> Decimal | None:
    """``part`` as a percentage of a positive ``whole``."""
    return 100 * part / whole if whole > 0 else None


@dataclass(frozen=True)
class YearEnd:
    """The yearly summaries, and what couldn't be converted."""

    years: list[YearSummary]
    currency: str
    unconverted: set[str]


def years_shown(first_year: int, start_year: int | None, end_year: int) -> list[int]:
    """The years to show: from ``start_year`` (or up to `MAX_YEARS` back) to ``end_year``.

    At most `MAX_YEARS`, the latest, and none before ``first_year``.
    """
    start = start_year if start_year is not None else end_year - MAX_YEARS + 1
    return list(range(max(start, end_year - MAX_YEARS + 1, first_year), end_year + 1))


def year_end(
    entries: list[Directive],
    price_map: prices.PriceMap,
    classes: Mapping[str, Classification],
    account_types: AccountTypes,
    currency: str,
    years: list[int],
    today: datetime.date,
) -> YearEnd:
    """Summaries of the given (consecutive) years, valued in ``currency``."""
    unconverted: set[str] = set()
    summaries = [
        YearSummary(year, min(datetime.date(year + 1, 1, 1), today + ONE_DAY)) for year in years
    ]
    # Balances of assets and liabilities, snapshotted at each year's start and end.
    balances: dict[str, Inventory] = defaultdict(Inventory)
    by_year = {summary.year: summary for summary in summaries}
    boundaries = sorted({summary.start for summary in summaries} | {s.end for s in summaries})
    snapshots: dict[datetime.date, dict[str, Inventory]] = {}
    held = (account_types.assets, account_types.liabilities)
    for txn in entries:
        if not isinstance(txn, Transaction):
            continue
        _snapshot(boundaries, balances, snapshots, txn.date)
        summary = by_year.get(txn.date.year)
        counted = summary and txn.date < summary.end
        for posting in txn.postings:
            root = get_account_type(posting.account)
            if root in held:
                balances[posting.account].add_position(posting)
            if not counted:
                continue
            if root in (account_types.income, account_types.expenses):
                value = _flow_value(posting, currency, price_map, txn.date, unconverted)
                if root == account_types.income:
                    summary.income -= value
                else:
                    summary.expenses += value
                    category = account_lib.join(*account_lib.split(posting.account)[:2])
                    summary.expenses_by_category[category] += value
    _snapshot(boundaries, balances, snapshots, datetime.date.max)

    for summary in summaries:
        start, end = snapshots[summary.start], snapshots[summary.end]
        start_values = _values(start, currency, price_map, summary.start - ONE_DAY, unconverted)
        end_values = _values(end, currency, price_map, summary.end - ONE_DAY, unconverted)
        summary.holdings_start = _by_group(start_values, classes)
        summary.holdings = _by_group(end_values, classes)
        summary.debts = _debts(
            entries, summary, classes, currency, price_map, start_values, end_values, unconverted
        )
    return YearEnd(summaries, currency, unconverted)


def _group(account: str, classes: Mapping[str, Classification]) -> str:
    return classes[account].group if account in classes else OTHER


def _by_group(
    values: Mapping[str, Decimal], classes: Mapping[str, Classification]
) -> dict[str, Decimal]:
    totals = {group: Decimal(0) for group in GROUPS}
    for account, value in values.items():
        totals[_group(account, classes)] += value
    return totals


def _snapshot(
    boundaries: list[datetime.date],
    balances: Mapping[str, Inventory],
    snapshots: dict[datetime.date, dict[str, Inventory]],
    date: datetime.date,
) -> None:
    """Copy the balances as of each boundary up to ``date``, removing it from ``boundaries``.

    Balances as of a boundary date are those before it: entries are processed in
    date order, so they're copied before the first entry on or after it.
    """
    while boundaries and boundaries[0] <= date:
        snapshots[boundaries.pop(0)] = {account: Inventory(i) for account, i in balances.items()}


def _flow_value(
    posting: Posting,
    currency: str,
    price_map: prices.PriceMap,
    date: datetime.date,
    unconverted: set[str],
) -> Decimal:
    """A posting's value in ``currency`` on its date, or 0 if it can't be converted."""
    amount = convert.convert_amount(convert.get_weight(posting), currency, price_map, date)
    if amount.currency != currency:
        unconverted.add(amount.currency)
        return Decimal(0)
    return amount.number


def _values(
    balances: Mapping[str, Inventory],
    currency: str,
    price_map: prices.PriceMap,
    date: datetime.date,
    unconverted: set[str],
) -> dict[str, Decimal]:
    """Each account's market value in ``currency`` on the date, or its cost without a price."""
    values: dict[str, Decimal] = defaultdict(Decimal)
    for account, inventory in balances.items():
        for position in inventory:
            amount = convert.convert_position(position, currency, price_map, date)
            if amount.currency != currency and position.cost:
                # No market price yet: value it at cost.
                cost = convert.get_cost(position)
                amount = convert.convert_amount(cost, currency, price_map, date)
            if amount.currency != currency:
                unconverted.add(amount.currency)
                continue
            values[account] += amount.number
    return values


def _debts(
    entries: list[Directive],
    summary: YearSummary,
    classes: Mapping[str, Classification],
    currency: str,
    price_map: prices.PriceMap,
    start_values: Mapping[str, Decimal],
    end_values: Mapping[str, Decimal],
    unconverted: set[str],
) -> list[Debt]:
    """The year's loans with a balance or activity."""
    debts: dict[str, Debt] = {}
    for account in start_values.keys() | end_values.keys():
        if _group(account, classes) == DEBT and (
            start_values.get(account) or end_values.get(account)
        ):
            # Owed amounts are positive.
            debts[account] = Debt(
                account,
                start=-start_values.get(account, Decimal(0)),
                end=-end_values.get(account, Decimal(0)),
            )
    for txn in entries:
        if not isinstance(txn, Transaction) or not summary.start <= txn.date < summary.end:
            continue
        for posting in txn.postings:
            if _group(posting.account, classes) != DEBT:
                continue
            debt = debts.setdefault(posting.account, Debt(posting.account))
            value = _flow_value(posting, currency, price_map, txn.date, unconverted)
            if value > 0:
                debt.paid += value
            else:
                debt.borrowed -= value
    return sorted(debts.values(), key=lambda item: item.account)
