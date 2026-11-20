"""The Cash Flow report's calculations: a cash-flow statement from cash-flow roles.

Accounts with the ``cash`` role (see `beancount_sg.cash_flow_roles`) are the cash
whose change the statement explains. Every other account's change over the
period is a line in the section of its role, ``operating``, ``investing`` or
``financing``, as its effect on cash: money in is positive, money out negative.
E.g. a salary is +, groceries are -, buying shares is - (investing), and paying
down a mortgage is - (financing).

Income and expense accounts are rolled up to their top-level category (e.g.
``Expenses:Food``); balance sheet accounts are listed as they are.

Since every transaction balances, the lines add up to the change in cash, valued
at each transaction's date. Cash at the start and end is valued at its market
value then: the difference, if any (e.g. from exchange rates moving while cash is
held in another currency), is shown as its own line, so the statement always
reconciles.

The statement also totals the spending (expense accounts) over the 12 months up
to the period's end, for the emergency fund: how many months of that average
spending cash at the end covers. It uses 12 months whatever the period, so a
short or partial period doesn't make it seasonal.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core import prices
from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Directive, Transaction
from beancount.core.inventory import Inventory

from beancount_sg.cash_flow_roles import (
    CASH,
    FINANCING,
    INVESTING,
    OPERATING,
    Role,
    default_role,
)

from .._valuation import market_values, posting_value

ACTIVITIES = (OPERATING, INVESTING, FINANCING)
ONE_DAY = datetime.timedelta(days=1)


@dataclass
class Statement:
    """A period's cash flows, by activity and line, in one currency.

    ``end`` is the day after the period's last day.
    """

    begin: datetime.date
    end: datetime.date
    currency: str
    # Each activity's lines: an account (or category) and its effect on cash.
    sections: dict[str, dict[str, Decimal]] = field(
        default_factory=lambda: {activity: defaultdict(Decimal) for activity in ACTIVITIES}
    )
    # Cash accounts' values at the start and end.
    cash_start: dict[str, Decimal] = field(default_factory=dict)
    cash_end: dict[str, Decimal] = field(default_factory=dict)
    # Spending over the 12 months up to the end: the expense accounts' total.
    trailing_expenses: Decimal = Decimal(0)
    unconverted: set[str] = field(default_factory=set)

    def lines(self, activity: str) -> list[tuple[str, Decimal]]:
        """An activity's non-zero lines, the largest (in or out) first."""
        found = [(line, value) for line, value in self.sections[activity].items() if value]
        return sorted(found, key=lambda item: (-abs(item[1]), item[0]))

    def total(self, activity: str) -> Decimal:
        return sum(self.sections[activity].values(), Decimal(0))

    @property
    def net_change(self) -> Decimal:
        """The activities' total effect on cash."""
        return sum((self.total(activity) for activity in ACTIVITIES), Decimal(0))

    @property
    def cash_start_total(self) -> Decimal:
        return sum(self.cash_start.values(), Decimal(0))

    @property
    def cash_end_total(self) -> Decimal:
        return sum(self.cash_end.values(), Decimal(0))

    @property
    def valuation_change(self) -> Decimal:
        """The change in cash's value the activities don't explain, e.g. exchange rates."""
        return self.cash_end_total - self.cash_start_total - self.net_change

    @property
    def trailing_start(self) -> datetime.date:
        """The first day of the 12 months up to the end."""
        return _year_before(self.end)

    @property
    def monthly_expenses(self) -> Decimal:
        """Average spending per month over the 12 months up to the end."""
        return self.trailing_expenses / 12

    @property
    def months_of_cash(self) -> Decimal | None:
        """How many months of average spending (see `monthly_expenses`) cash at the end covers."""
        if self.monthly_expenses <= 0:
            return None
        return self.cash_end_total / self.monthly_expenses

    @property
    def cash_accounts(self) -> list[str]:
        """The cash accounts with a balance at the start or end."""
        return sorted(
            account
            for account in self.cash_start.keys() | self.cash_end.keys()
            if self.cash_start.get(account) or self.cash_end.get(account)
        )


def _year_before(date: datetime.date) -> datetime.date:
    """The same day a year earlier (February 28th for February 29th)."""
    if (date.month, date.day) == (2, 29):
        return date.replace(year=date.year - 1, day=28)
    return date.replace(year=date.year - 1)


def role_of(account: str, roles: Mapping[str, Role], account_types: AccountTypes) -> str:
    """An account's role, or the default for an account that wasn't opened."""
    return roles[account].role if account in roles else default_role(account, account_types)


def line_of(account: str, account_types: AccountTypes) -> str:
    """The statement line an account's flows go to: its top-level category for income
    and expenses, else the account itself."""
    if get_account_type(account) in (account_types.income, account_types.expenses):
        return account_lib.join(*account_lib.split(account)[:2])
    return account


def statement(
    entries: Iterable[Directive],
    price_map: prices.PriceMap,
    roles: Mapping[str, Role],
    account_types: AccountTypes,
    currency: str,
    begin: datetime.date,
    end: datetime.date,
) -> Statement:
    """The cash-flow statement from ``begin`` up to (not including) ``end``."""
    result = Statement(begin, end, currency)
    start_balances: dict[str, Inventory] = defaultdict(Inventory)
    end_balances: dict[str, Inventory] = defaultdict(Inventory)
    trailing_start = result.trailing_start
    for txn in entries:
        if not isinstance(txn, Transaction) or txn.date >= end:
            continue
        for posting in txn.postings:
            role = role_of(posting.account, roles, account_types)
            if role == CASH:
                end_balances[posting.account].add_position(posting)
                if txn.date < begin:
                    start_balances[posting.account].add_position(posting)
                continue
            in_period = txn.date >= begin
            spent = (
                txn.date >= trailing_start
                and get_account_type(posting.account) == account_types.expenses
            )
            if not in_period and not spent:
                continue
            value = posting_value(posting, currency, price_map, txn.date, result.unconverted)
            if in_period:
                # Money into the account is money out of cash, and the reverse.
                result.sections[role][line_of(posting.account, account_types)] -= value
            if spent:
                result.trailing_expenses += value
    result.cash_start = market_values(
        start_balances, currency, price_map, begin - ONE_DAY, result.unconverted
    )
    result.cash_end = market_values(
        end_balances, currency, price_map, end - ONE_DAY, result.unconverted
    )
    return result


@dataclass(frozen=True)
class Interval:
    """An interval's cash flows by activity, dated by its last day."""

    date: datetime.date
    totals: dict[str, Decimal]


def by_interval(
    entries: Sequence[Directive],
    price_map: prices.PriceMap,
    roles: Mapping[str, Role],
    account_types: AccountTypes,
    currency: str,
    ranges: Iterable[tuple[datetime.date, datetime.date]],
) -> list[Interval]:
    """Each date range's cash flows by activity, for a chart."""
    found = []
    for begin, end in ranges:
        part = statement(entries, price_map, roles, account_types, currency, begin, end)
        found.append(
            Interval(end - ONE_DAY, {activity: part.total(activity) for activity in ACTIVITIES})
        )
    return found
