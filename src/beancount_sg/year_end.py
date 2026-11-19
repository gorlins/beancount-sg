"""Yearly financial metrics: net worth, income and spending, savings, and debt.

Accounts are classified by their *cash-flow role*, declared with metadata on
their ``open`` directive, the same key Beancount.io's cash-flow report uses:

    2020-01-01 open Assets:Brokerage
      cash-flow-role: "investing"

The roles are ``cash`` (cash and equivalents), ``investing``, ``financing`` and
``operating``. An account without a declaration takes its nearest parent's, or
else a default from its name and type:

- Assets: ``cash`` if the name contains Cash, Checking, Savings or Bank, else
  ``investing``.
- Liabilities: ``operating`` if the name contains Card (credit cards, which are
  everyday spending), else ``financing`` (loans: debt).
- Equity: ``financing``. Income and Expenses: ``operating``.

An unknown role is reported as an error and the default used. The roles group
net worth into cash, investments, debt (financing liabilities, e.g. a mortgage)
and other (e.g. credit card balances), and pick out the debt whose paydown is
shown.

All values are in one currency (the ledger's first operating currency): holdings
at their market value on the date (or at cost, if they have no price yet), and
income and spending at their value on each transaction's date. Amounts that
can't be converted, for lack of prices, are left out and their currencies
reported.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import NamedTuple

from beancount.core import account as account_lib
from beancount.core import convert, prices
from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Directive, Meta, Open, Posting, Transaction
from beancount.core.inventory import Inventory

ROLE_KEY = "cash-flow-role"
CASH, OPERATING, INVESTING, FINANCING = "cash", "operating", "investing", "financing"
ROLES = (CASH, OPERATING, INVESTING, FINANCING)
# Names of asset accounts that default to cash, and of liabilities that default
# to operating (credit cards).
CASH_NAMES = re.compile(r"cash|checking|savings|bank", re.IGNORECASE)
CARD_NAMES = re.compile(r"card", re.IGNORECASE)
MAX_YEARS = 5
ONE_DAY = datetime.timedelta(days=1)


class RoleError(NamedTuple):
    """Conforms to `beancount.core.data.BeancountError`."""

    source: Meta
    message: str
    entry: Directive


@dataclass(frozen=True)
class Role:
    """An account's cash-flow role, and the account that declared it, if any."""

    role: str
    declared_by: str | None = None  # None when inferred from the name and type


def account_roles(
    entries: Iterable[Directive], account_types: AccountTypes
) -> tuple[dict[str, Role], list[RoleError]]:
    """Every opened account's role: declared, inherited from a parent, or inferred."""
    opens = {entry.account: entry for entry in entries if isinstance(entry, Open)}
    declared: dict[str, str] = {}
    errors: list[RoleError] = []
    for account, entry in opens.items():
        value = entry.meta.get(ROLE_KEY)
        if value is None:
            continue
        if value in ROLES:
            declared[account] = value
        else:
            message = f"{account}: unknown {ROLE_KEY} {value!r}, using the default"
            errors.append(RoleError(entry.meta, message, entry))
    roles = {}
    for account in opens:
        declarer = next(
            (parent for parent in _self_and_parents(account) if parent in declared), None
        )
        if declarer:
            roles[account] = Role(declared[declarer], declarer)
        else:
            roles[account] = Role(_default_role(account, account_types))
    return roles, errors


def _self_and_parents(account: str) -> Iterable[str]:
    while account:
        yield account
        account = account_lib.parent(account)


def _default_role(account: str, account_types: AccountTypes) -> str:
    root = get_account_type(account)
    if root == account_types.assets:
        return CASH if CASH_NAMES.search(account) else INVESTING
    if root == account_types.liabilities:
        return OPERATING if CARD_NAMES.search(account) else FINANCING
    if root == account_types.equity:
        return FINANCING
    return OPERATING


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
    net_worth_start: Decimal = Decimal(0)
    # Net worth at the end of the year, by role group: cash, investing, debt, other.
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
    def net_worth(self) -> Decimal:
        return sum(self.holdings.values(), Decimal(0))

    @property
    def net_worth_change(self) -> Decimal:
        return self.net_worth - self.net_worth_start

    @property
    def savings(self) -> Decimal:
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
        """Annual expenses as a percentage of net worth at the start of the year.

        Like a withdrawal rate in retirement: what share of your net worth a
        year's spending would take.
        """
        if self.net_worth_start <= 0:
            return None
        return 100 * self.annual_expenses / self.net_worth_start

    @property
    def years_of_spending(self) -> Decimal | None:
        """Net worth at the end of the year, in years of annual expenses, if it's positive."""
        if self.net_worth <= 0 or self.annual_expenses <= 0:
            return None
        return self.net_worth / self.annual_expenses

    @property
    def months_of_cash(self) -> Decimal | None:
        """Cash at the end of the year, in months of annual expenses."""
        if self.annual_expenses <= 0:
            return None
        return 12 * self.holdings.get(CASH, Decimal(0)) / self.annual_expenses

    @property
    def top_categories(self) -> list[tuple[str, Decimal]]:
        return sorted(self.expenses_by_category.items(), key=lambda item: -item[1])


# Net worth groups, by role, and for liabilities, by debt (financing) or other.
DEBT, OTHER = "debt", "other"
GROUPS = (CASH, INVESTING, DEBT, OTHER)


@dataclass(frozen=True)
class YearEnd:
    """The yearly summaries, and what couldn't be converted."""

    years: list[YearSummary]
    currency: str
    unconverted: set[str]


def years_ending(end_year: int, first_year: int, count: int = MAX_YEARS) -> list[int]:
    """Up to ``count`` years ending with ``end_year``, none before ``first_year``."""
    return list(range(max(end_year - count + 1, first_year), end_year + 1))


def year_end(
    entries: list[Directive],
    roles: Mapping[str, Role],
    account_types: AccountTypes,
    currency: str,
    years: list[int],
    today: datetime.date,
) -> YearEnd:
    """Summaries of the given (consecutive) years, valued in ``currency``."""
    price_map = prices.build_price_map(entries)
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
        summary.net_worth_start = sum(
            _values(start, currency, price_map, summary.start - ONE_DAY, unconverted).values(),
            Decimal(0),
        )
        values = _values(end, currency, price_map, summary.end - ONE_DAY, unconverted)
        summary.holdings = {group: Decimal(0) for group in GROUPS}
        for account, value in values.items():
            summary.holdings[_group(account, roles, account_types)] += value
        summary.debts = _debts(
            entries, summary, roles, account_types, currency, price_map, start, end, unconverted
        )
    return YearEnd(summaries, currency, unconverted)


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


def _group(account: str, roles: Mapping[str, Role], account_types: AccountTypes) -> str:
    role = roles[account].role if account in roles else _default_role(account, account_types)
    if get_account_type(account) == account_types.liabilities:
        return DEBT if role == FINANCING else OTHER
    return role if role in (CASH, INVESTING) else OTHER


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
    roles: Mapping[str, Role],
    account_types: AccountTypes,
    currency: str,
    price_map: prices.PriceMap,
    start: Mapping[str, Inventory],
    end: Mapping[str, Inventory],
    unconverted: set[str],
) -> list[Debt]:
    """The year's debts (financing liabilities) with a balance or activity."""
    debts: dict[str, Debt] = {}
    start_values = _values(start, currency, price_map, summary.start - ONE_DAY, unconverted)
    end_values = _values(end, currency, price_map, summary.end - ONE_DAY, unconverted)
    for account in start_values.keys() | end_values.keys():
        if _group(account, roles, account_types) == DEBT and (
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
            if _group(posting.account, roles, account_types) != DEBT:
                continue
            debt = debts.setdefault(posting.account, Debt(posting.account))
            value = _flow_value(posting, currency, price_map, txn.date, unconverted)
            if value > 0:
                debt.paid += value
            else:
                debt.borrowed -= value
    return sorted(debts.values(), key=lambda item: item.account)
