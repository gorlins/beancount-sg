"""A Fava report of cash flows: where cash came from and went, by activity.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.cash_flow"

The "Cash Flow" report is a cash-flow statement, classifying accounts by their
``cash-flow-role`` metadata, or their names (see `beancount_sg.cash_flow_roles`),
the convention Beancount.io's cash-flow report uses. It explains the change in
cash (accounts with the ``cash`` role) over the period by every other account's
flows, in operating, investing and financing sections; see
`beancount_sg.ext.cash_flow.statement`.

The period is Fava's time filter, up to today, or the last 12 months without one.
Fava's account and advanced filters apply, as on Fava's own reports. The page has:

- Cards in plain terms: net income (operating), invested or withdrawn from
  investments (investing), debt paid down or borrowed (financing), the change in
  cash, and the emergency fund: how many months of average spending over the last
  12 months cash covers. Only net income is colored, green for a surplus and red
  for a deficit: investing and financing flows aren't good or bad by their sign.
- A Sankey diagram of where cash came from and went: income, expenses, investing,
  debt and the change in cash (drawn with ECharts; see `beancount_sg.ext.echarts`).
- The statement: each activity's lines and total in its own direction, like the
  cards (see `SECTIONS`), and the change in cash.
- Charts of each card's amount per interval (Fava's interval menu).
- The reconciliation: each cash account at the start and end, with the change
  the activities explain.
- How each account is classified, declared or by its name, and any invalid roles.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from beancount.core import prices
from beancount.core.account_types import get_account_type
from beancount.parser.options import get_account_types
from fava.context import g
from fava.core import FilteredLedger
from fava.core.charts import DateAndBalanceWithBudget
from fava.core.inventory import SimpleCounterInventory
from fava.ext import FavaExtensionBase
from fava.internal_api import BarChart
from fava.util.date import dateranges, local_today
from flask import request, url_for

from beancount_sg.cash_flow_roles import CASH, FINANCING, INVESTING, OPERATING, Role, account_roles
from beancount_sg.ext.echarts import ECharts

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


def tone(activity: str | None, value: Decimal) -> str:
    """A total's CSS class: colored only where its sign is clearly good or bad.

    Only operating cash is: a surplus (income over spending) is good, and a
    deficit bad. Investing and financing go either way: money out of cash into
    investments, or to repay a loan, is usually good.
    """
    if activity != OPERATING or not value:
        return "neutral"
    return "good" if value > 0 else "bad"


@dataclass(frozen=True)
class Card:
    """An activity's total as a card: a plain title, the amount, and how it's made up."""

    title: str
    amount: str
    tone: str
    detail: str


# Each activity's card title and detail, by whether its total is money into cash.
# Investing and financing are named for which way the money went, and shown
# without a sign; net income keeps its sign.
CARDS = {
    (OPERATING, True): ("Net income", "income minus spending"),
    (OPERATING, False): ("Net income", "income minus spending"),
    (INVESTING, True): ("Withdrawn from investments", "taken out, minus money put in"),
    (INVESTING, False): ("Invested", "put into investments, minus withdrawals"),
    (FINANCING, True): ("Borrowed", "new borrowing, minus loan and card payments"),
    (FINANCING, False): ("Debt paid down", "loan and card payments, minus new borrowing"),
}


def card(activity: str, value: Decimal) -> Card:
    """The card for an activity's total."""
    title, detail = CARDS[(activity, value > 0)]
    amount = money(value) if activity == OPERATING else balance(abs(value))
    return Card(title, amount, tone(activity, value), detail)


@dataclass(frozen=True)
class Section:
    """How the page shows an activity: in its own direction, like its card."""

    title: str  # for the total, and the chart
    sign: int  # turns an effect on cash into the activity's direction
    lines: str  # what a line's sign means


# The statement's lines are effects on cash. The page turns investing and
# financing around, so that money into investments and debt paid down are
# positive, as on the cards: e.g. invested 9,640 rather than -9,640.
SECTIONS = {
    OPERATING: Section("Net income", 1, "income (+) and spending (−)"),
    INVESTING: Section("Invested", -1, "money put in (+) or taken out (−)"),
    FINANCING: Section("Debt paid down", -1, "payments (+) or new borrowing (−)"),
}


# The Sankey diagram's colors: income, spending, investments, debt and cash.
COLORS = {
    "income": "#2e9d5b",
    "spending": "#d9534f",
    "investments": "#3a7bd5",
    "debt": "#e08a2b",
    "cash": "#8a8f98",
}


class CashFlow(ECharts, FavaExtensionBase):
    """Fava report of cash flows by activity."""

    report_title = "Cash Flow"
    has_js_module = True
    activities = ACTIVITIES
    one_day = ONE_DAY
    # For the template.
    money = staticmethod(money)
    balance = staticmethod(balance)
    tone = staticmethod(tone)
    card = staticmethod(card)
    sections = SECTIONS

    def period(self) -> tuple[datetime.date, datetime.date]:
        """Fava's time filter, or the last 12 months: the first day, and the day after the last.

        The last 12 months are this month to date and the 11 before it. A time
        filter ends today at the latest, e.g. this year is year-to-date.
        """
        today = local_today()
        date_range = g.filtered.date_range
        if date_range:
            return date_range.begin, max(date_range.begin, min(date_range.end, today + ONE_DAY))
        months = today.year * 12 + today.month - 1 - 11
        return datetime.date(months // 12, months % 12 + 1, 1), today + ONE_DAY

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

    def charts(self, result: Statement) -> list[BarChart]:
        """Per interval of Fava's interval menu: each card's amount, as a chart to switch to.

        Each is in its own direction, like the cards: net income, invested, debt
        paid down, and the change in cash.
        """
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
        series = [
            (
                SECTIONS[activity].title,
                # `or 0`: turned around, a zero is -0.
                [SECTIONS[activity].sign * i.totals[activity] or Decimal(0) for i in intervals],
            )
            for activity in ACTIVITIES
        ]
        series.append(("Change in cash", [sum(i.totals.values(), Decimal(0)) for i in intervals]))
        return [
            BarChart(
                title,
                [
                    DateAndBalanceWithBudget(
                        interval.date, SimpleCounterInventory({result.currency: value}), {}, {}
                    )
                    for interval, value in zip(intervals, values, strict=True)
                ],
            )
            for title, values in series
        ]

    def sankey(self, result: Statement) -> dict[str, object]:
        """The Sankey diagram, as an ECharts option: what flowed into cash, and out.

        Its nodes are the accounting totals, not their accounts: income and
        expenses (gross), investing and debt (net, named for which way they
        went, like the cards), and what was added to or taken from cash, which
        balances the two sides.
        """
        account_types = get_account_types(self.ledger.options)
        income = sum(
            (
                value
                for line, value in result.lines(OPERATING)
                if get_account_type(line) == account_types.income
            ),
            Decimal(0),
        )
        income_statement = url_for("report", report_name="income_statement", time=self._time())
        balance_sheet = url_for("report", report_name="balance_sheet", time=self._time())
        # Each total's effect on cash (+ into it), its names into and out of cash,
        # its color, and its page.
        totals = [
            (income, "Income", "Income", "income", income_statement),
            (
                result.total(OPERATING) - income,
                "Expenses",
                "Expenses",
                "spending",
                income_statement,
            ),
            (
                result.total(INVESTING),
                "Withdrawn from investments",
                "Invested",
                "investments",
                balance_sheet,
            ),
            (result.total(FINANCING), "Borrowed", "Debt paid down", "debt", balance_sheet),
            # Cash that grew takes money out of the flows, and the reverse.
            (-result.net_change, "Taken from cash", "Added to cash", "cash", None),
        ]
        nodes: list[dict[str, object]] = [
            {
                "name": "Cash",
                "itemStyle": {"color": COLORS["cash"]},
                "label": {"position": "top"},
            }
        ]
        links = []
        for effect, into, out_of, kind, url in totals:
            if not effect:
                continue
            name = into if effect > 0 else out_of
            nodes.append(
                {
                    "name": name,
                    "url": url,
                    "itemStyle": {"color": COLORS[kind]},
                    "label": {
                        "position": "left" if effect > 0 else "right",
                        "formatter": f"{name} {balance(abs(effect))}",
                    },
                }
            )
            source, target = (name, "Cash") if effect > 0 else ("Cash", name)
            links.append({"source": source, "target": target, "value": float(abs(effect))})
        return {
            "animation": False,
            "series": [
                {
                    "type": "sankey",
                    "left": 200,
                    "right": 200,
                    "top": 24,
                    "bottom": 8,
                    "nodeWidth": 14,
                    "nodeGap": 10,
                    "layoutIterations": 0,
                    "lineStyle": {"color": "gradient", "curveness": 0.5, "opacity": 0.45},
                    "emphasis": {"focus": "adjacency"},
                    "data": nodes,
                    "links": links,
                }
            ],
        }

    @staticmethod
    def interval_label() -> str:
        """The charts' heading: Fava's interval, e.g. Monthly."""
        return g.interval.label

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
