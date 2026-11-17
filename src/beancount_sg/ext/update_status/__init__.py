"""A Fava report of when each tracked account was last balanced.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.update_status"

The "Update Status" report lists the open accounts with Fava's
``fava-uptodate-indication`` metadata on their ``open`` directive (see also
`beancount_sg.plugins.uptodate_subaccounts`), each with:

- Fava's status dot: green if the account's last entry is a passing balance
  assertion, yellow if it's a transaction, red if it's a failing assertion.
  Clicking a yellow or red dot copies balance directives for today, as in
  Fava's sidebar.
- The date of its last entry, linking to it.
- The date of its last balance assertion, passing or failing, linking to it, and how many
  days ago that was. An account that's never been balanced counts from the
  day it was opened.
- Its last balance: each currency's last asserted amount.
- The difference between the ledger and that: blank if the dot is green; for
  red, the failing assertion's difference; for yellow, the current balance
  minus the last asserted amount (what a new assertion would need to confirm).

Above the table, "Up to date as of" is the oldest of those assertion dates. A balance
assertion checks the balance at the start of its day, so it confirms the
transactions before that date.

The report covers the whole ledger, whatever Fava's filters, since it's about
the accounts' current state.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from beancount.core.amount import Amount
from beancount.core.data import Balance, Close, Directive, Open, Transaction
from fava.beans.funcs import hash_entry
from fava.core.accounts import AccountData
from fava.ext import FavaExtensionBase
from fava.util.date import local_today

# The Open metadata key Fava uses to show an account's status.
UPTODATE_KEY = "fava-uptodate-indication"

# Status dots sort worst first.
STATUS_ORDER = {"red": 0, "yellow": 1, "green": 2}


@dataclass(frozen=True)
class AccountStatus:
    """A tracked account's last balance assertions and current balance."""

    account: str
    opened: datetime.date
    # Each currency's last balance assertion, whether it passed or failed.
    last_assertions: dict[str, Balance]
    balance: list[Amount]

    @property
    def last_balance(self) -> Balance | None:
        """The account's last balance assertion in any currency, passing or failing."""
        return max(self.last_assertions.values(), key=lambda entry: entry.date, default=None)

    @property
    def balanced_as_of(self) -> datetime.date:
        """The date of the last balance assertion, or else of the open."""
        last = self.last_balance
        return last.date if last else self.opened

    def days_since_balanced(self, today: datetime.date) -> int:
        return (today - self.balanced_as_of).days

    @property
    def last_balance_amounts(self) -> list[Amount]:
        """The amounts of each currency's last balance assertion."""
        return [self.last_assertions[currency].amount for currency in sorted(self.last_assertions)]

    def difference(self, status: str | None) -> list[Amount]:
        """The ledger's balance minus the last asserted balance, per currency.

        By Fava's status dot: none when ``green`` (the last entry is a passing
        assertion); for ``red`` (a failing one), the failing assertions'
        differences; otherwise the current balance minus each currency's last
        asserted amount (or zero, if it's never been asserted). Either way, a
        positive difference means the ledger has more than was asserted.
        """
        if status == "green":
            return []
        if status == "red":
            return [
                entry.diff_amount
                for _, entry in sorted(self.last_assertions.items())
                if entry.diff_amount
            ]
        differences: dict[str, Decimal] = defaultdict(Decimal)
        for amount in self.balance:
            differences[amount.currency] += amount.number
        for currency, entry in self.last_assertions.items():
            differences[currency] -= entry.amount.number
        return [
            Amount(number, currency) for currency, number in sorted(differences.items()) if number
        ]


def account_statuses(entries: Iterable[Directive]) -> list[AccountStatus]:
    """The open accounts with ``fava-uptodate-indication`` metadata, by account name."""
    entries = list(entries)
    closed = {entry.account for entry in entries if isinstance(entry, Close)}
    tracked = {
        entry.account: entry.date
        for entry in entries
        if isinstance(entry, Open) and entry.meta.get(UPTODATE_KEY) and entry.account not in closed
    }
    last_assertions: dict[str, dict[str, Balance]] = defaultdict(dict)
    balances: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for entry in entries:
        if isinstance(entry, Balance) and entry.account in tracked:
            previous = last_assertions[entry.account].get(entry.amount.currency)
            if not previous or entry.date >= previous.date:
                last_assertions[entry.account][entry.amount.currency] = entry
        elif isinstance(entry, Transaction):
            for posting in entry.postings:
                if posting.account in tracked:
                    balances[posting.account][posting.units.currency] += posting.units.number
    return [
        AccountStatus(
            account,
            opened,
            last_assertions[account],
            [
                Amount(number, currency)
                for currency, number in sorted(balances[account].items())
                if number
            ],
        )
        for account, opened in sorted(tracked.items())
    ]


class UpdateStatus(FavaExtensionBase):
    """Fava report of when each tracked account was last balanced."""

    report_title = "Update Status"

    def statuses(self) -> list[AccountStatus]:
        """The tracked accounts' statuses, from the whole ledger."""
        return account_statuses(self.ledger.all_entries)

    @staticmethod
    def up_to_date_as_of(statuses: list[AccountStatus]) -> datetime.date | None:
        """The oldest of the accounts' last balance dates."""
        return min((status.balanced_as_of for status in statuses), default=None)

    def account_data(self, account: str) -> AccountData:
        """Fava's data for the account: its status dot, last entry and balance directives."""
        return self.ledger.accounts[account]

    @staticmethod
    def status_order(status: str | None) -> int:
        """A status dot's sort key: red, yellow, green, then none."""
        return STATUS_ORDER.get(status or "", len(STATUS_ORDER))

    @staticmethod
    def today() -> datetime.date:
        return local_today()

    @staticmethod
    def entry_hash(entry: Directive) -> str:
        """Fava's id for an entry, to link to it."""
        return hash_entry(entry)
