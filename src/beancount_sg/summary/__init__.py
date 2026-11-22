"""A summary of a ledger's finances for someone who doesn't use Beancount.

Written for e.g. a spouse taking over the household's finances, so it covers the
real-world accounts, not the ledger's categories. Make it as a PDF with the
``bean-summary`` command (see `beancount_sg.summary.cli`), or view it in Fava with
the `beancount_sg.ext.summary` report. `summarize` makes it, as of a date:

- **Open accounts**: each asset and liability account that's open, with the
  institution that holds it and who owns it (``institution`` and ``owner``
  metadata on its ``open`` directive, or a parent's), the last 4 digits of its
  number (``account-number``), and its value, in groups: bank accounts and cash
  (the ``cash`` cash-flow role, see `beancount_sg.cash_flow_roles`), investments
  and property (other assets), and loans and credit cards (liabilities). Within
  a group, accounts are by institution.
- **Secured loans**: an asset with a loan opened under the matching path (e.g.
  ``Assets:Home`` and ``Liabilities:Home:Mortgage``), with its value, what's owed
  and the equity: value minus what's owed.
- **Bills**: the accounts marked ``bill`` on their ``open`` directive, e.g. a
  utility's expense account or the mortgage, with their last payment, which
  account paid it, and what they came to over the last 12 months. ``bill: TRUE``
  uses the account's name; a string names the bill, e.g. ``bill: "Electric"``.
- **Closed accounts**: asset and liability accounts that were closed, with their
  institutions, owners, the last 4 digits of their numbers and when, so they're
  recognized if they turn up.

Values are at market value in the first operating currency where there are
prices, and as they are otherwise.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core import convert, prices
from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Close, Directive, Open, Transaction
from beancount.core.inventory import Inventory
from beancount.parser.options import get_account_types

from beancount_sg.cash_flow_roles import CASH, Role, account_roles

ACCOUNT_NUMBER_KEY = "account-number"
# Who holds an account, and who owns it, e.g. "Joint (Scott and Jane)": on its
# open directive, or a parent's.
INSTITUTION_KEY, OWNER_KEY = "institution", "owner"
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
    institution: str | None = None
    owner: str | None = None
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
    meta = {entry.account: entry.meta for entry in entries if isinstance(entry, Open)}
    # Parents of other accounts, e.g. one opened only to give its subaccounts an
    # institution: left out unless they hold something themselves.
    parents = {parent for name in meta for parent in account_lib.parents(name) if parent != name}
    found = []
    for entry in entries:
        if not isinstance(entry, Open):
            continue
        if entry.account in parents and not any(values.get(entry.account, {}).values()):
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
                _inherited(meta, entry.account, INSTITUTION_KEY),
                _inherited(meta, entry.account, OWNER_KEY),
                values.get(entry.account, {}),
                closed.get(entry.account),
            )
        )
    found.sort(
        key=lambda item: (
            list(GROUPS).index(item.group),
            (item.institution or "").lower(),
            item.account,
        )
    )
    return [item for item in found if not item.closed], [item for item in found if item.closed]


def _inherited(meta: Mapping[str, Mapping[str, object]], account: str, key: str) -> str | None:
    """A metadata value on the account's ``open`` directive, or its nearest parent's."""
    for name in account_lib.parents(account):
        if key in meta.get(name, {}):
            return str(meta[name][key])
    return None


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


@dataclass(frozen=True)
class Summary:
    """Everything the summary shows, as of a date."""

    title: str
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

    @property
    def missing_details(self) -> list[Account]:
        """The open accounts without an institution or an owner, to fill in."""
        return [item for item in self.open_accounts if not item.institution or not item.owner]

    @staticmethod
    def money(values: Amounts) -> str:
        """Amounts for a reader: to the cent, with thousands separators and currencies."""
        shown = [
            f"{number:,.2f} {currency}" for currency, number in sorted(values.items()) if number
        ]
        return ", ".join(shown) if shown else "0.00"


def values_by_account(
    entries: Iterable[Directive],
    currency: str | None,
    price_map: prices.PriceMap,
    date: datetime.date,
) -> tuple[dict[str, Amounts], dict[str, Amounts]]:
    """Each account's value, and its value with its subaccounts' (and for each parent).

    At market value in ``currency`` where there are prices on the date, and as
    they are otherwise.
    """
    balances: dict[str, Inventory] = defaultdict(Inventory)
    for entry in entries:
        if isinstance(entry, Transaction):
            for posting in entry.postings:
                balances[posting.account].add_position(posting)
    values: dict[str, Amounts] = {}
    totals: dict[str, Amounts] = defaultdict(dict)
    for account, inventory in balances.items():
        value: dict[str, Decimal] = defaultdict(Decimal)
        for position in inventory:
            amount = (
                convert.convert_position(position, currency, price_map, date)
                if currency
                else position.units
            )
            value[amount.currency] += amount.number
        values[account] = dict(value)
        for name in account_lib.parents(account):
            for unit, number in value.items():
                totals[name][unit] = totals[name].get(unit, Decimal(0)) + number
    return values, dict(totals)


def summarize(
    entries: list[Directive], options: Mapping[str, object], date: datetime.date
) -> Summary:
    """The summary of a ledger's entries (e.g. from `beancount.loader.load_file`) on a date."""
    account_types = get_account_types(options)
    entries = [entry for entry in entries if entry.date <= date]
    currencies = options["operating_currency"]
    currency = currencies[0] if currencies else None
    values, totals = values_by_account(entries, currency, prices.build_price_map(entries), date)
    roles, _ = account_roles(entries, account_types)
    open_accounts, closed_accounts = accounts(entries, roles, account_types, values)
    debts = {unit: -number for unit, number in totals.get(account_types.liabilities, {}).items()}
    return Summary(
        str(options["title"]),
        date,
        currency,
        open_accounts,
        closed_accounts,
        secured_loans(open_accounts, totals, account_types),
        bills(entries, account_types, date),
        totals.get(account_types.assets, {}),
        debts,
    )
