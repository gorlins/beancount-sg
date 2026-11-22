"""A Fava report summarizing the household's finances for someone who doesn't use Beancount.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.summary"

The "Financial Summary" report is written for a spouse or family member taking
over the finances, e.g. in case of death: which real-world accounts exist and
what they're worth, the equity in a home or car with a loan on it, the bills to
keep paying, and the accounts that were closed. A "Download PDF" link gives the
same as a PDF to print or keep somewhere safe. See
`beancount_sg.ext.summary.contents` for what each section holds and the
metadata it reads.

The report covers the whole ledger as of today, whatever Fava's filters.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from beancount.parser.options import get_account_types
from fava.core.conversion import cost_or_value
from fava.core.tree import Tree
from fava.ext import FavaExtensionBase, extension_endpoint
from fava.util.date import local_today
from flask import Response

from beancount_sg.cash_flow_roles import account_roles

from .contents import (
    GROUPS,
    Account,
    Amounts,
    Bill,
    SecuredLoan,
    accounts,
    bills,
    secured_loans,
    subtract,
)
from .pdf import render


@dataclass(frozen=True)
class Summary:
    """Everything the report shows, as of a date."""

    date: datetime.date
    currency: str | None
    open_accounts: list[Account]
    closed_accounts: list[Account]
    secured_loans: list[SecuredLoan]
    bills: list[Bill]
    assets: Amounts
    debts: Amounts  # positive

    def group(self, group: str) -> list[Account]:
        return [item for item in self.open_accounts if item.group == group]

    @property
    def net_worth(self) -> Amounts:
        return subtract(self.assets, self.debts)


class FinancialSummary(FavaExtensionBase):
    """Fava report summarizing the finances for a non-technical reader."""

    report_title = "Financial Summary"
    groups = GROUPS

    @staticmethod
    def amounts(values: Amounts) -> str:
        """Amounts for a reader: whole cents, with thousands separators and currencies."""
        shown = [
            f"{number:,.2f} {currency}" for currency, number in sorted(values.items()) if number
        ]
        return ", ".join(shown) if shown else "0.00"

    def summary(self) -> Summary:
        """The summary as of today."""
        today = local_today()
        options = self.ledger.options
        account_types = get_account_types(options)
        entries = [entry for entry in self.ledger.all_entries if entry.date <= today]
        currencies = options["operating_currency"]
        currency = currencies[0] if currencies else None
        tree = Tree(entries)
        # Market values in the operating currency, where there are prices.
        conversion = currency or "units"
        values = {
            name: dict(cost_or_value(node.balance, conversion, self.ledger.prices, today))
            for name, node in tree.items()
        }
        totals = {
            name: dict(cost_or_value(node.balance_children, conversion, self.ledger.prices, today))
            for name, node in tree.items()
        }
        roles, _ = account_roles(self.ledger.all_entries_by_type.Open, account_types)
        open_accounts, closed_accounts = accounts(entries, roles, account_types, values)
        debts = {
            currency: -number
            for currency, number in totals.get(account_types.liabilities, {}).items()
        }
        return Summary(
            today,
            currency,
            open_accounts,
            closed_accounts,
            secured_loans(open_accounts, totals, account_types),
            bills(entries, account_types, today),
            totals.get(account_types.assets, {}),
            debts,
        )

    @extension_endpoint
    def pdf(self) -> Response:
        """The summary as a PDF, to download."""
        summary = self.summary()
        title = self.ledger.options["title"]
        response = Response(render(summary, title, self.amounts), mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f'attachment; filename="financial-summary-{summary.date}.pdf"'
        )
        return response
