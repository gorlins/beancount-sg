"""The Year in Review's calculations: net worth groups and yearly summaries.

Net worth is assets minus liabilities (what's owed), in groups:

- **Cash**: cash and savings accounts.
- **Investments**: other assets, unless they're property.
- **Property**: assets you live in or use rather than invest: real estate,
  vehicles and other personal property.

An asset's group follows its line on the Financial Summary's personal financial
statement (see `beancount_sg.summary.lines`): declared with ``asset-type`` on its
``open`` directive, a parent's, or the commodity it holds, or else inferred from
its cash-flow role (see `beancount_sg.cash_flow_roles`), its name, and the loans
opened under its path.
- **Debt**: liabilities with the ``financing`` role (the default), credit cards
  included.
- **Other**: liabilities declared with another role.

Investable assets are cash and investments: what spending could be drawn from.

Income and expense accounts are income and expenses, unless they're declared
with a cash-flow role other than ``operating``, which keeps them out of income,
expenses, savings and the spending ratios:

- ``investing``: **investment returns**, e.g. capital gains. A gain realized when
  investments are sold and bought again (say, in a retirement plan's rollover)
  never reached your spending money; it's in net worth already, where the
  investments are.
- Any other role, e.g. ``financing``: **transfers**, e.g. an expense account that
  loan payments pass through on their way to the loan. The loan's balance
  already counts them, in debt paid down.

Each year's metrics are one of three kinds:

- **Balances** at the year's end (for the current year, today): net worth and
  its groups, investable assets, and each loan's balance.
- **Flows** during the year (for the current year, so far): income, expenses,
  savings, the savings rate, debt paid down, and investment returns.
- **Spending ratios**: the 12 months of spending up to the year's end, against
  balances then: the withdrawal rate, spending / net worth, and the emergency
  fund. For a whole year, the 12 months are the year; for the current year,
  they're the last 12 months, so its ratios compare with whole years'.

All values are in one currency: holdings at their market value on the date (or
at cost, if they have no price yet), and income and spending at their value on
each transaction's date. Amounts that can't be converted, for lack of prices,
are left out and their currencies reported.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core import convert, prices
from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Directive, Open, Posting, Transaction
from beancount.core.inventory import Inventory

from beancount_sg.cash_flow_roles import CASH, FINANCING, INVESTING, OPERATING, Role
from beancount_sg.summary import lines

INVESTMENTS, PROPERTY, DEBT, OTHER = "investments", "property", "debt", "other"
GROUPS = (CASH, INVESTMENTS, PROPERTY, DEBT, OTHER)
# Income and expense accounts that aren't income or expenses: investment returns, or
# transfers (e.g. to a loan) counted elsewhere.
RETURNS, TRANSFERS = "investment returns", "transfers"
# The statement lines in the cash and property groups: the rest are investments.
CASH_LINES = ("cash", "savings")
PROPERTY_LINES = ("real-estate", "automobiles", "personal-property")
MAX_YEARS = 5
ONE_DAY = datetime.timedelta(days=1)


@dataclass(frozen=True)
class Classification:
    """An account's net worth group (or, for income and expenses, `RETURNS` or
    `TRANSFERS`), and why."""

    group: str
    reason: str


def classify(
    entries: Iterable[Directive], roles: Mapping[str, Role], account_types: AccountTypes
) -> dict[str, Classification]:
    """Each asset and liability's net worth group, and the income and expense accounts
    declared with a role other than ``operating``: investment returns (``investing``)
    or transfers."""
    entries = list(entries)
    placed = lines(entries, roles, account_types)
    found = {}
    for entry in entries:
        if not isinstance(entry, Open):
            continue
        account = entry.account
        root = get_account_type(account)
        role = roles[account]
        if root == account_types.assets:
            line, reason = placed[account]
            if line.key in CASH_LINES:
                group = CASH
            elif line.key in PROPERTY_LINES:
                group = PROPERTY
            else:
                group = INVESTMENTS
            found[account] = Classification(group, f"{line.title.lower()}: {reason}")
        elif root == account_types.liabilities:
            found[account] = _liability(role)
        elif root in (account_types.income, account_types.expenses) and role.role != OPERATING:
            group = RETURNS if role.role == INVESTING else TRANSFERS
            found[account] = Classification(group, _role_reason(role))
    return found


def _liability(role: Role) -> Classification:
    return Classification(DEBT if role.role == FINANCING else OTHER, _role_reason(role))


def _role_reason(role: Role) -> str:
    if role.declared:
        return f"{role.role}, declared on {role.declared_by}"
    return f"{role.role}, by default"


@dataclass(frozen=True)
class Debt:
    """A debt's balance at the start and end of a year: owed amounts are positive."""

    account: str
    start: Decimal
    end: Decimal

    @property
    def paid_down(self) -> Decimal:
        """The fall in the balance: payments minus new borrowing (negative if it grew).

        A credit card paid in full each month comes to about zero.
        """
        return self.start - self.end


@dataclass
class YearSummary:
    """A year's metrics, in one currency.

    ``end`` is the day after the last day counted: the next January 1st, or for
    the current year, tomorrow (so the year is year-to-date). Balances are as of
    the end, flows are during the year, and spending ratios use the 12 months of
    spending up to the end (``trailing_expenses``).
    """

    year: int
    end: datetime.date
    # Net worth by group, at the start and end of the year. Liabilities are negative.
    holdings_start: dict[str, Decimal] = field(default_factory=dict)
    holdings: dict[str, Decimal] = field(default_factory=dict)
    income: Decimal = Decimal(0)
    expenses: Decimal = Decimal(0)
    expenses_by_category: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    # Expenses over the 12 months up to the end: for a whole year, the year's.
    trailing_expenses: Decimal = Decimal(0)
    # Income less costs in accounts that are investment returns, e.g. capital gains:
    # not in income, expenses or savings.
    investment_returns: Decimal = Decimal(0)
    debts: list[Debt] = field(default_factory=list)

    @property
    def start(self) -> datetime.date:
        return datetime.date(self.year, 1, 1)

    @property
    def complete(self) -> bool:
        """Whether the whole year is counted, rather than year-to-date."""
        return self.end == datetime.date(self.year + 1, 1, 1)

    @property
    def trailing_start(self) -> datetime.date:
        """The first day of the 12 months up to the end."""
        return _year_before(self.end)

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
    def spending_rate(self) -> Decimal | None:
        """The last 12 months' expenses as a percentage of net worth at the end."""
        return _percentage(self.trailing_expenses, self.net_worth)

    @property
    def withdrawal_rate(self) -> Decimal | None:
        """The last 12 months' expenses as a percentage of investable assets at the end.

        Like a withdrawal rate in retirement: what share of the cash and
        investments you could draw on a year's spending would take.
        """
        return _percentage(self.trailing_expenses, self.investable)

    @property
    def months_of_cash(self) -> Decimal | None:
        """Cash at the end, in months of the last 12 months' average expenses."""
        if self.trailing_expenses <= 0:
            return None
        return 12 * self.holdings.get(CASH, Decimal(0)) / self.trailing_expenses

    @property
    def debt_paid_down(self) -> Decimal:
        return sum((debt.paid_down for debt in self.debts), Decimal(0))

    @property
    def top_categories(self) -> list[tuple[str, Decimal]]:
        return sorted(self.expenses_by_category.items(), key=lambda item: -item[1])


def _year_before(date: datetime.date) -> datetime.date:
    """The same day a year earlier (February 28th for February 29th)."""
    if (date.month, date.day) == (2, 29):
        return date.replace(year=date.year - 1, day=28)
    return date.replace(year=date.year - 1)


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
    boundaries = sorted({summary.start for summary in summaries} | {s.end for s in summaries})
    snapshots: dict[datetime.date, dict[str, Inventory]] = {}
    held = (account_types.assets, account_types.liabilities)
    for txn in entries:
        if not isinstance(txn, Transaction):
            continue
        _snapshot(boundaries, balances, snapshots, txn.date)
        # The years whose 12 months of spending include this date.
        windows = [s for s in summaries if s.trailing_start <= txn.date < s.end]
        for posting in txn.postings:
            root = get_account_type(posting.account)
            if root in held:
                balances[posting.account].add_position(posting)
            if not windows or root not in (account_types.income, account_types.expenses):
                continue
            value = _flow_value(posting, currency, price_map, txn.date, unconverted)
            group = _group(posting.account, classes)
            for summary in windows:
                if group in (RETURNS, TRANSFERS):
                    if group == RETURNS and txn.date >= summary.start:
                        summary.investment_returns -= value
                    continue
                if root == account_types.expenses:
                    summary.trailing_expenses += value
                if txn.date < summary.start:
                    continue
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
        summary.debts = _debts(classes, start_values, end_values)
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
    classes: Mapping[str, Classification],
    start_values: Mapping[str, Decimal],
    end_values: Mapping[str, Decimal],
) -> list[Debt]:
    """The year's debts with a balance at its start or end."""
    debts = []
    for account in sorted(start_values.keys() | end_values.keys()):
        start, end = start_values.get(account, Decimal(0)), end_values.get(account, Decimal(0))
        if _group(account, classes) == DEBT and (start or end):
            debts.append(Debt(account, start=-start, end=-end))  # owed amounts are positive
    return debts
