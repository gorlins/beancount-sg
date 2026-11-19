"""A Fava report of yearly financial metrics: a year-end dashboard.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.year_end"

The "Year in Review" report shows up to five years, ending with the last year
of Fava's time filter, or the current year without one (which is year-to-date).
Only the time filter's last year is used: the figures always cover whole years
of the whole ledger, since a filter on accounts or tags would make net worth
meaningless. It has:

- Key metrics per year: net worth (by cash, investments, debt and other), its
  change, income, expenses, savings and savings rate; spending as a percentage
  of net worth at the start of the year (a withdrawal rate, as a preview of
  retirement), net worth in years of spending, and cash in months of spending.
  For the current year, spending-based ratios use spending annualized from the
  year so far.
- Charts of net worth by year, and expenses by top-level category.
- Expenses by top-level category (e.g. ``Expenses:Food``) per year.
- Debt paydown in the last year: each loan's balance, new borrowing and
  payments.
- How each asset and liability account is classified.

Accounts are classified with ``cash-flow-role`` metadata, or by their names; see
`beancount_sg.year_end`.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from beancount.core.account_types import get_account_type
from beancount.core.data import Transaction
from beancount.parser.options import get_account_types
from fava.context import g
from fava.core.charts import DateAndBalanceWithBudget
from fava.core.inventory import SimpleCounterInventory
from fava.ext import FavaExtensionBase
from fava.internal_api import BarChart
from fava.util.date import local_today
from flask import url_for

from beancount_sg.year_end import (
    ONE_DAY,
    Role,
    YearEnd,
    YearSummary,
    account_roles,
    year_end,
    years_ending,
)


class YearInReview(FavaExtensionBase):
    """Fava report of yearly financial metrics."""

    report_title = "Year in Review"
    one_day = ONE_DAY

    def end_year(self) -> int:
        """The last year of Fava's time filter, or the current year."""
        date_range = g.filtered.date_range
        return (date_range.end - ONE_DAY).year if date_range else local_today().year

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

    def review(self) -> YearEnd | None:
        """The summaries of the years shown, or None without an operating currency."""
        currency = self.currency()
        if not currency:
            return None
        entries = self.ledger.all_entries
        first = next((entry.date.year for entry in entries if isinstance(entry, Transaction)), None)
        years = years_ending(self.end_year(), first) if first else []
        roles, _ = self.roles()
        account_types = get_account_types(self.ledger.options)
        return year_end(entries, roles, account_types, currency, years, local_today())

    def classified(self) -> list[tuple[str, Role]]:
        """The open asset and liability accounts, and their roles."""
        roles, _ = self.roles()
        account_types = get_account_types(self.ledger.options)
        held = (account_types.assets, account_types.liabilities)
        closed = {entry.account for entry in self.ledger.all_entries_by_type.Close}
        return [
            (account, role)
            for account, role in sorted(roles.items())
            if get_account_type(account) in held and account not in closed
        ]

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

    @staticmethod
    def charts(result: YearEnd) -> list[BarChart]:
        """Net worth at each year's end, and expenses by category per year."""
        currency = result.currency
        # Bars rather than a line, as there's one value per year. Clicking a bar's
        # date sets Fava's time filter to that year: this review, ending there.
        net_worth = [
            DateAndBalanceWithBudget(
                _last_day(year), SimpleCounterInventory({currency: year.net_worth}), {}, {}
            )
            for year in result.years
        ]
        expenses = [
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
        return [
            BarChart("Net worth", net_worth),
            BarChart("Expenses by category", expenses),
        ]


def _last_day(year: YearSummary) -> datetime.date:
    return year.end - ONE_DAY
