"""A Fava report of yearly financial metrics: a year-end dashboard.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.year_end"

The "Year in Review" report shows whole years, ending with the last year of
Fava's time filter, or the current year without one (which is year-to-date). A
time filter over a range of years, e.g. ``2022 - 2024``, shows those years; a
single year shows it and the four before. It shows at most five years.

Fava's account and advanced filters apply as on Fava's own reports, but the time
filter only picks the years: balances always include everything before them.

Metrics are balances at each year's end (for the current year, today), flows
during the year (so far), or spending ratios over the 12 months up to the year's
end; see `beancount_sg.ext.year_end.metrics`. The dashboard has:

- Cards with the final year's headline metrics and their change from the
  previous year: net worth, investable assets, income, expenses, savings rate,
  debt paid down, withdrawal rate and emergency fund.
- Charts of net worth per year (or assets and liabilities, stacked), and of
  expenses by category.
- Net worth (assets minus liabilities) by group.
- Income, expenses, savings and the savings rate per year, investment returns
  (income and expense accounts declared investing, e.g. capital gains, left out of
  income and savings), and the spending
  ratios: the withdrawal rate (spending as a share of investable assets: cash and
  investments), spending as a share of net worth, and the emergency fund.
- Expenses by top-level category (e.g. ``Expenses:Food``) per year, with a chart.
- Debt in the final year: each debt's balance at the start and end, and how much
  it was paid down.
- How each asset and liability account is classified.

Changes from the previous year are green when they're good and red when they're
bad. Accounts are classified by their ``cash-flow-role`` (see
`beancount_sg.cash_flow_roles`) and ``investable`` metadata, or their names; see
`beancount_sg.ext.year_end.metrics`.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from beancount.core import prices
from beancount.core.account_types import get_account_type
from beancount.core.data import Transaction
from beancount.parser.options import get_account_types
from fava.context import g
from fava.core import FilteredLedger
from fava.core.charts import DateAndBalanceWithBudget
from fava.core.inventory import SimpleCounterInventory
from fava.ext import FavaExtensionBase
from fava.internal_api import BarChart
from fava.util.date import local_today
from flask import request, url_for

from beancount_sg.cash_flow_roles import Role, account_roles, notable_accounts

from .metrics import (
    ONE_DAY,
    PROPERTY,
    Classification,
    YearEnd,
    YearSummary,
    classify,
    year_end,
    years_shown,
)


@dataclass(frozen=True)
class Change:
    """A metric's change from the previous year, and whether that's good."""

    diff: Decimal
    percent: Decimal | None  # relative to the previous value, if it isn't zero
    good: bool | None  # None when unchanged

    @property
    def tone(self) -> str:
        """The change's CSS class: good, bad or flat."""
        if self.good is None:
            return "flat"
        return "good" if self.good else "bad"

    @property
    def arrow(self) -> str:
        return "▲" if self.diff > 0 else "▼" if self.diff < 0 else "■"

    def label(self, unit: str = "money") -> str:
        """The change as shown: an amount and percentage, percentage ``points``, or a ``number``."""
        if not self.diff:
            return "no change"
        if unit == "points":
            return f"{_signed(self.diff, 1)} pts"
        if unit == "number":
            return _signed(self.diff, 1)
        percent = f" ({_signed(self.percent, 1)}%)" if self.percent is not None else ""
        return _signed(self.diff, 0) + percent


def _signed(value: Decimal, digits: int) -> str:
    """A number with a + or − sign (a minus, not a hyphen) and thousands separators."""
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):,.{digits}f}"


def change(
    current: Decimal | None, previous: Decimal | None, *, higher_is_better: bool = True
) -> Change | None:
    """The change from ``previous`` to ``current``, if both are known."""
    if current is None or previous is None:
        return None
    diff = current - previous
    percent = 100 * diff / abs(previous) if previous else None
    good = None if not diff else (diff > 0) == higher_is_better
    return Change(diff, percent, good)


def changes(
    values: Iterable[Decimal | None],
    years: list[YearSummary],
    *,
    higher_is_better: bool = True,
    flow: bool = False,
) -> list[Change | None]:
    """Each year's change from the previous year (None for the first).

    A ``flow`` (e.g. income) isn't compared for a year-to-date year, whose total
    isn't comparable with a whole year's.
    """
    values = list(values)
    found: list[Change | None] = [None]
    for i in range(1, len(values)):
        if flow and not years[i].complete:
            found.append(None)
        else:
            found.append(change(values[i], values[i - 1], higher_is_better=higher_is_better))
    return found


def money(value: Decimal | None) -> str:
    """An amount rounded to whole units, with thousands separators."""
    return "—" if value is None else f"{value:,.0f}"


class YearInReview(FavaExtensionBase):
    """Fava report of yearly financial metrics."""

    report_title = "Year in Review"
    one_day = ONE_DAY
    # For the template.
    changes = staticmethod(changes)
    money = staticmethod(money)

    @staticmethod
    def category_values(result: YearEnd, category: str) -> list[Decimal]:
        """A category's expenses in each year."""
        return [year.expenses_by_category.get(category, Decimal(0)) for year in result.years]

    def years_filtered(self) -> tuple[int | None, int]:
        """The first and last years of Fava's time filter, or no first year and this year.

        The first year is None unless the filter spans more than one year.
        """
        date_range = g.filtered.date_range
        if not date_range:
            return None, local_today().year
        start, end = date_range.begin.year, (date_range.end - ONE_DAY).year
        return (start if start < end else None), end

    def currency(self) -> str | None:
        """The ledger's first operating currency, which values are shown in."""
        currencies = self.ledger.options["operating_currency"]
        return currencies[0] if currencies else None

    def roles(self) -> tuple[dict[str, Role], list[str]]:
        """Each account's role, and problems with declared roles."""
        roles, errors = account_roles(
            self.ledger.all_entries_by_type.Open, get_account_types(self.ledger.options)
        )
        return roles, [error.message for error in errors]

    def _classes(self) -> dict[str, Classification]:
        roles, _ = self.roles()
        return classify(
            self.ledger.all_entries_by_type.Open, roles, get_account_types(self.ledger.options)
        )

    def review(self) -> YearEnd | None:
        """The summaries of the years shown, or None without an operating currency."""
        currency = self.currency()
        if not currency:
            return None
        # Fava's account and advanced filters, but not its time filter: balances
        # need everything before the years shown.
        entries = FilteredLedger(
            self.ledger, account=request.args.get("account"), filter=request.args.get("filter")
        ).entries
        account_types = get_account_types(self.ledger.options)
        # Years start with the first with income or expenses: before that, there are
        # at most opening balances, which the next year starts from anyway.
        flows = (account_types.income, account_types.expenses)
        first = next(
            (
                entry.date.year
                for entry in entries
                if isinstance(entry, Transaction)
                and any(get_account_type(p.account) in flows for p in entry.postings)
            ),
            None,
        )
        start, end = self.years_filtered()
        years = years_shown(first, start, end) if first else []
        # Prices from the whole ledger, which the filters could leave out.
        price_map = prices.build_price_map(self.ledger.all_entries)
        return year_end(
            entries, price_map, self._classes(), account_types, currency, years, local_today()
        )

    def classified(self) -> list[tuple[str, Role, Classification]]:
        """The open accounts that are classified, their roles and net worth groups: assets,
        liabilities, and income and expense accounts that are investment returns or
        transfers.

        Only those two levels deep (e.g. ``Assets:Bank``), and deeper ones in a
        different group from their parent: the rest are as their parent.
        """
        roles, _ = self.roles()
        closed = {entry.account for entry in self.ledger.all_entries_by_type.Close}
        classes = {
            account: classification
            for account, classification in self._classes().items()
            if account not in closed
        }
        groups = {account: classification.group for account, classification in classes.items()}
        return [(account, roles[account], classes[account]) for account in notable_accounts(groups)]

    @staticmethod
    def categories(result: YearEnd) -> list[str]:
        """The expense categories in any year, the last year's largest first."""
        last = result.years[-1].expenses_by_category
        found = {category for year in result.years for category in year.expenses_by_category}
        return sorted(found, key=lambda category: (-last.get(category, Decimal(0)), category))

    @staticmethod
    def year_url(year: int) -> str:
        """The income statement for a year."""
        return url_for("report", report_name="income_statement", time=str(year))

    @staticmethod
    def account_url(account: str, year: int) -> str:
        """An account's page for a year."""
        return url_for("account", name=account, time=str(year))

    def net_worth_charts(self, result: YearEnd) -> list[BarChart]:
        """Net worth at each year's end, and assets and liabilities, stacked.

        Fava can't draw a line over bars, so these are two charts, switched between
        below them. Clicking a bar's date sets Fava's time filter to that year: this
        review, ending there. Clicking assets or liabilities opens their account page.
        """
        account_types = get_account_types(self.ledger.options)
        currency = result.currency
        net_worth = [
            DateAndBalanceWithBudget(
                _last_day(year), SimpleCounterInventory({currency: year.net_worth}), {}, {}
            )
            for year in result.years
        ]
        assets_and_liabilities = [
            DateAndBalanceWithBudget(
                _last_day(year),
                SimpleCounterInventory({currency: year.net_worth}),
                {
                    account_types.assets: SimpleCounterInventory({currency: _assets(year)}),
                    account_types.liabilities: SimpleCounterInventory(
                        {currency: year.net_worth - _assets(year)}
                    ),
                },
                {},
            )
            for year in result.years
        ]
        return [
            BarChart("Net worth", net_worth),
            BarChart("Assets & liabilities", assets_and_liabilities),
        ]

    @staticmethod
    def expenses_chart(result: YearEnd) -> BarChart:
        """Expenses by category per year, stacked."""
        currency = result.currency
        bars = [
            DateAndBalanceWithBudget(
                _last_day(year),
                SimpleCounterInventory({currency: year.expenses}),
                {
                    category: SimpleCounterInventory({currency: value})
                    for category, value in year.expenses_by_category.items()
                },
                {},
            )
            for year in result.years
        ]
        return BarChart("Expenses by category", bars)


def _assets(year: YearSummary) -> Decimal:
    """Assets at the year's end: cash, investments and property."""
    return year.investable + year.holdings[PROPERTY]


def _last_day(year: YearSummary) -> datetime.date:
    return year.end - ONE_DAY
