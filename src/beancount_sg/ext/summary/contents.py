"""The Financial Summary's contents: accounts, secured loans and bills, as of a date.

Written for someone who doesn't use Beancount, e.g. a spouse taking over the
household's finances, so it covers the real-world accounts, not the ledger's
categories:

- **Open accounts**: each asset and liability account that's open, with its
  value and the last 4 digits of its number (``account-number`` metadata on its
  ``open`` directive), in groups: bank accounts and cash (the ``cash`` cash-flow
  role, see `beancount_sg.cash_flow_roles`), investments and property (other
  assets), and loans and credit cards (liabilities).
- **Secured loans**: an asset with a loan opened under the matching path (e.g.
  ``Assets:Home`` and ``Liabilities:Home:Mortgage``), with its value, what's owed
  and the equity: value minus what's owed.
- **Bills**: the accounts marked ``bill`` on their ``open`` directive, e.g. a
  utility's expense account or the mortgage, with their last payment, which
  account paid it, and what they came to over the last 12 months. ``bill: TRUE``
  uses the account's name; a string names the bill, e.g. ``bill: "Electric"``.
- **Closed accounts**: asset and liability accounts that were closed, with the
  last 4 digits of their numbers and when, so they're recognized if they turn up.

Values are at market value in one currency where there are prices (Fava's
conversion), and as they are otherwise.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core import convert
from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Close, Directive, Open, Transaction

from beancount_sg.cash_flow_roles import CASH, Role

ACCOUNT_NUMBER_KEY = "account-number"
BILL_KEY = "bill"
BANK, INVESTMENTS, DEBTS = (
    "Bank accounts and cash",
    "Investments and property",
    "Loans and credit cards",
)
# The groups, in order, and what their accounts' amounts are called.
GROUPS = {BANK: "Balance", INVESTMENTS: "Value", DEBTS: "Owed"}
ONE_YEAR = datetime.timedelta(days=365)

# An amount per currency.
Amounts = dict[str, Decimal]


def last4(number: object) -> str | None:
    """The last 4 digits of an account number, or None without digits."""
    digits = re.sub(r"\D", "", str(number))
    return digits[-4:] if digits else None


def label(account: str) -> str:
    """An account's name for a reader, without its root: e.g. ``Bank › Checking``."""
    return " › ".join(account_lib.split(account)[1:]) or account


@dataclass(frozen=True)
class Account:
    """An asset or liability account, as the summary shows it."""

    account: str
    group: str
    opened: datetime.date
    number: str | None  # the last 4 digits
    value: Amounts = field(default_factory=dict)  # liabilities are negative
    closed: datetime.date | None = None

    @property
    def label(self) -> str:
        return label(self.account)

    @property
    def amount(self) -> Amounts:
        """Its value, or for a loan or card, what's owed: as a reader expects, positive."""
        return subtract({}, self.value) if self.group == DEBTS else self.value


@dataclass(frozen=True)
class SecuredLoan:
    """An asset, the loans opened under its path, and the equity in it."""

    asset: str
    loans: list[str]
    value: Amounts
    owed: Amounts  # positive

    @property
    def label(self) -> str:
        return label(self.asset)

    @property
    def loan_labels(self) -> str:
        return ", ".join(label(loan) for loan in self.loans)

    @property
    def equity(self) -> Amounts:
        return subtract(self.value, self.owed)


@dataclass
class Bill:
    """An account marked as a bill, and its payments: transactions adding to it."""

    name: str
    account: str
    last_paid: datetime.date | None = None
    last_amount: Amounts = field(default_factory=dict)
    paid_from: list[str] = field(default_factory=list)  # by the last payment
    payments: int = 0  # in the last 12 months
    yearly: Amounts = field(default_factory=dict)  # in the last 12 months

    @property
    def paid_from_labels(self) -> str:
        return ", ".join(label(account) for account in self.paid_from)


def subtract(left: Mapping[str, Decimal], right: Mapping[str, Decimal]) -> Amounts:
    """``left`` minus ``right``, per currency."""
    found: dict[str, Decimal] = defaultdict(Decimal, left)
    for currency, number in right.items():
        found[currency] -= number
    return dict(found)


def accounts(
    entries: Iterable[Directive],
    roles: Mapping[str, Role],
    account_types: AccountTypes,
    values: Mapping[str, Amounts],
) -> tuple[list[Account], list[Account]]:
    """The open and the closed asset and liability accounts, by group and name.

    ``values`` are the accounts' values, e.g. from `values_by_account`.
    """
    entries = list(entries)
    closed = {entry.account: entry.date for entry in entries if isinstance(entry, Close)}
    found = []
    for entry in entries:
        if not isinstance(entry, Open):
            continue
        root = get_account_type(entry.account)
        if root == account_types.assets:
            group = BANK if roles[entry.account].role == CASH else INVESTMENTS
        elif root == account_types.liabilities:
            group = DEBTS
        else:
            continue
        number = entry.meta.get(ACCOUNT_NUMBER_KEY)
        found.append(
            Account(
                entry.account,
                group,
                entry.date,
                last4(number) if number is not None else None,
                values.get(entry.account, {}),
                closed.get(entry.account),
            )
        )
    found.sort(key=lambda item: (list(GROUPS).index(item.group), item.account))
    return [item for item in found if not item.closed], [item for item in found if item.closed]


def secured_loans(
    open_accounts: Iterable[Account], totals: Mapping[str, Amounts], account_types: AccountTypes
) -> list[SecuredLoan]:
    """The assets with a loan opened under their matching path, and what's owed on them.

    ``totals`` are each account's value with its subaccounts', e.g.
    ``Liabilities:Home`` for ``Liabilities:Home:Mortgage``.
    """
    open_accounts = list(open_accounts)
    loans = [item.account for item in open_accounts if item.group == DEBTS]
    found = []
    for item in open_accounts:
        if get_account_type(item.account) != account_types.assets:
            continue
        path = account_lib.join(account_types.liabilities, *account_lib.split(item.account)[1:])
        matching = [loan for loan in loans if loan == path or loan.startswith(path + ":")]
        if matching:
            owed = {currency: -number for currency, number in totals.get(path, {}).items()}
            found.append(SecuredLoan(item.account, matching, totals.get(item.account, {}), owed))
    return found


def bills(
    entries: Iterable[Directive],
    account_types: AccountTypes,
    today: datetime.date,
) -> list[Bill]:
    """The accounts marked as bills, with their payments, by name.

    A payment is a transaction adding to the bill's account (e.g. an expense, or a
    loan payment). Its amount is what left the accounts that paid it: the asset
    and liability accounts it took money from.
    """
    entries = list(entries)
    found: dict[str, Bill] = {}
    for entry in entries:
        if isinstance(entry, Open) and BILL_KEY in entry.meta:
            name = entry.meta[BILL_KEY]
            if name is False:
                continue
            found[entry.account] = Bill(
                name if isinstance(name, str) else label(entry.account), entry.account
            )
    held = (account_types.assets, account_types.liabilities)
    for txn in entries:
        if not isinstance(txn, Transaction) or txn.date > today:
            continue
        for bill in {p.account for p in txn.postings if p.account in found and p.units.number > 0}:
            payment = found[bill]
            paid: dict[str, Decimal] = defaultdict(Decimal)
            sources = []
            for posting in txn.postings:
                weight = convert.get_weight(posting)
                funds = posting.account != bill and get_account_type(posting.account) in held
                if funds and weight.number < 0:
                    paid[weight.currency] -= weight.number
                    sources.append(posting.account)
            payment.last_paid = txn.date
            payment.last_amount = dict(paid)
            payment.paid_from = sources
            if txn.date > today - ONE_YEAR:
                payment.payments += 1
                for currency, number in paid.items():
                    payment.yearly[currency] = payment.yearly.get(currency, Decimal(0)) + number
    return sorted(found.values(), key=lambda item: item.name.lower())
