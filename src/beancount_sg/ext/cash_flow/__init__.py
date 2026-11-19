"""A Fava report of cash flows: where cash came from and went, by activity.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.cash_flow"

The "Cash Flow" report is a cash-flow statement, classifying accounts by their
``cash-flow-role`` metadata, or their names (see `beancount_sg.cash_flow_roles`),
the convention Beancount.io's cash-flow report uses. It explains the change in
cash (accounts with the ``cash`` role) over the period by every other account's
flows, in operating, investing and financing sections; see
`beancount_sg.ext.cash_flow.statement`.

The period is Fava's time filter, or this year (to date) without one. Fava's
account and advanced filters apply, as on Fava's own reports. The page has:

- Cards with the net change in cash and each activity's total.
- The statement: each activity's lines and total, and the net change in cash.
- A chart of each activity's flows per interval (Fava's interval menu).
- The reconciliation: each cash account at the start and end, with the change
  the activities explain.
- How each account is classified, declared or by its name, and any unknown roles.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from beancount.core import prices
from beancount.parser.options import get_account_types
from fava.context import g
from fava.core import FilteredLedger
from fava.core.charts import DateAndBalanceWithBudget
from fava.core.inventory import SimpleCounterInventory
from fava.ext import FavaExtensionBase
from fava.internal_api import BarChart
from fava.util.date import dateranges, local_today
from flask import request, url_for

from beancount_sg.cash_flow_roles import CASH, Role, account_roles

from .statement import ACTIVITIES, ONE_DAY, Statement, by_interval, role_of, statement


def money(value: Decimal | None) -> str:
    """An amount rounded to whole units, with thousands separators and a sign."""
    if value is None:
        return "—"
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):,.0f}"


def balance(value: Decimal) -> str:
    """A balance rounded to whole units, with thousands separators."""
    return f"{value:,.0f}"


def tone(value: Decimal) -> str:
    """A flow's CSS class: money in is good, money out bad."""
    return "good" if value > 0 else "bad" if value < 0 else "flat"


class CashFlow(FavaExtensionBase):
    """Fava report of cash flows by activity."""

    report_title = "Cash Flow"
    has_js_module = True
    activities = ACTIVITIES
    one_day = ONE_DAY
    # For the template.
    money = staticmethod(money)
    balance = staticmethod(balance)
    tone = staticmethod(tone)

    def period(self) -> tuple[datetime.date, datetime.date]:
        """Fava's time filter, or this year to date: the first day, and the day after the last."""
        date_range = g.filtered.date_range
        if date_range:
            return date_range.begin, date_range.end
        today = local_today()
        return datetime.date(today.year, 1, 1), today + ONE_DAY

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

    def _entries(self) -> list:
        # Fava's account and advanced filters, but not its time filter: the cash at
        # the start needs everything before the period.
        return FilteredLedger(
            self.ledger, account=request.args.get("account"), filter=request.args.get("filter")
        ).entries

    def statement(self) -> Statement | None:
        """The period's statement, or None without an operating currency."""
        currency = self.currency()
        if not currency:
            return None
        roles, _ = self.roles()
        begin, end = self.period()
        price_map = prices.build_price_map(self.ledger.all_entries)
        account_types = get_account_types(self.ledger.options)
        return statement(self._entries(), price_map, roles, account_types, currency, begin, end)

    def chart(self, result: Statement) -> BarChart:
        """Each activity's flows per interval of Fava's interval menu, stacked."""
        roles, _ = self.roles()
        price_map = prices.build_price_map(self.ledger.all_entries)
        account_types = get_account_types(self.ledger.options)
        # Intervals clipped to the period, at most Fava's 100 for a bar chart.
        ranges = [
            (date_range.begin, date_range.end)
            for date_range in dateranges(result.begin, result.end, g.interval, complete=False)
        ][-100:]
        intervals = by_interval(
            self._entries(), price_map, roles, account_types, result.currency, ranges
        )
        currency = result.currency
        bars = [
            DateAndBalanceWithBudget(
                interval.date,
                SimpleCounterInventory({currency: sum(interval.totals.values(), Decimal(0))}),
                {
                    activity.capitalize(): SimpleCounterInventory({currency: value})
                    for activity, value in interval.totals.items()
                },
                {},
            )
            for interval in intervals
        ]
        return BarChart(f"Cash flows by activity ({g.interval.label})", bars)

    def chart_links(self) -> dict[str, str]:
        """The chart's activities, and the Fava report each should link to."""
        return {
            "Operating": url_for("report", report_name="income_statement", time=self._time()),
            "Investing": url_for("report", report_name="balance_sheet", time=self._time()),
            "Financing": url_for("report", report_name="balance_sheet", time=self._time()),
        }

    def _time(self) -> str:
        """The period, as a Fava time filter."""
        begin, end = self.period()
        return f"{begin} - {end - ONE_DAY}"

    def account_url(self, account: str) -> str:
        """An account's page, for the period."""
        return url_for("account", name=account, time=self._time())

    def classified(self) -> list[tuple[str, Role]]:
        """The open accounts other than cash, and their roles."""
        roles, _ = self.roles()
        closed = {entry.account for entry in self.ledger.all_entries_by_type.Close}
        account_types = get_account_types(self.ledger.options)
        return [
            (account, role)
            for account, role in sorted(roles.items())
            if account not in closed and role_of(account, roles, account_types) != CASH
        ]

    def cash_accounts(self) -> list[tuple[str, Role]]:
        """The open accounts counted as cash, and their roles."""
        roles, _ = self.roles()
        closed = {entry.account for entry in self.ledger.all_entries_by_type.Close}
        return [
            (account, role)
            for account, role in sorted(roles.items())
            if account not in closed and role.role == CASH
        ]
