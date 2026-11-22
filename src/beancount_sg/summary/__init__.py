"""A personal financial statement of a ledger, for someone who doesn't use Beancount.

Written for e.g. a spouse taking over the household's finances, so it covers the
real-world accounts, not the ledger's categories. Make it as a PDF with the
``bean-summary`` command (see `beancount_sg.summary.cli`), or view it in Fava with
the `beancount_sg.ext.summary` report. `summarize` makes it, as of a date.

It follows the personal financial statement banks ask for, e.g. with a loan
application: the US Small Business Administration's Form 413, whose asset and
liability lines Fannie Mae's mortgage application (Form 1003) mostly shares.

- **Statement**: each asset and liability line's total (`ASSET_LINES`,
  `LIABILITY_LINES`), and net worth.
- **Accounts**: each line's open accounts, with the institution that holds each
  and its owner (``institution`` and ``owner`` metadata on its ``open``
  directive, or a parent's), the last 4 digits of its number
  (``account-number``), and its value or what's owed.
- **Real estate and vehicles**: as the form's "real estate owned" schedule, each
  property with its value, and each loan opened under its matching path (e.g.
  ``Assets:Home`` and ``Liabilities:Home:Mortgage``) with its lender, number,
  balance and last payment, and the equity.
- **Bills**: the accounts marked ``bill``, e.g. a utility's expense account or the
  mortgage, with their last payment, which account paid it, and what they came
  to over the last 12 months. ``bill: TRUE`` uses the account's name; a string
  names the bill, e.g. ``bill: "Electric"``.
- **Closed accounts**: with their institutions, owners, the last 4 digits of
  their numbers and dates, so they're recognized if they turn up.

An account's line is declared with ``asset-type`` or ``liability-type`` metadata
on its ``open`` directive (or a parent's), e.g. ``asset-type: "real-estate"``; for
an asset, also on the ``commodity`` directive of what it holds. Otherwise it's
inferred from what the ledger already says (see `asset_line` and
`liability_line`): its cash-flow role (`beancount_sg.cash_flow_roles`), its name,
and the loans opened under its path.

Values are at market value in the first operating currency where there are
prices, and as they are otherwise.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core import convert, prices
from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Close, Commodity, Directive, Open, Transaction
from beancount.core.inventory import Inventory
from beancount.parser.options import get_account_types

from beancount_sg.cash_flow_roles import CASH, Role, account_roles

# Metadata on an account's open directive (the first four, or a parent's).
INSTITUTION_KEY, OWNER_KEY = "institution", "owner"
# An account's line, by its key: also on a commodity's directive, for assets.
ASSET_TYPE_KEY, LIABILITY_TYPE_KEY = "asset-type", "liability-type"
ACCOUNT_NUMBER_KEY, BILL_KEY = "account-number", "bill"
ONE_YEAR = datetime.timedelta(days=365)

# An amount per currency.
Amounts = dict[str, Decimal]


@dataclass(frozen=True)
class Line:
    """A line of the statement: its key (an ``asset-type`` or ``liability-type``), and title."""

    key: str
    title: str
    liability: bool


# Form 413's lines, in its order.
ASSET_LINES = (
    Line("cash", "Cash on hand and in banks", False),
    Line("savings", "Savings accounts", False),
    Line("retirement", "IRA or other retirement accounts", False),
    Line("receivables", "Accounts and notes receivable", False),
    Line("life-insurance", "Life insurance (cash surrender value)", False),
    Line("stocks-bonds", "Stocks and bonds", False),
    Line("real-estate", "Real estate", False),
    Line("automobiles", "Automobiles", False),
    Line("personal-property", "Other personal property", False),
    Line("other-assets", "Other assets", False),
)
LIABILITY_LINES = (
    Line("credit-cards", "Credit cards and accounts payable", True),
    Line("notes-payable", "Notes payable to banks and others", True),
    Line("auto-loans", "Installment loans (auto)", True),
    Line("installment-loans", "Installment loans (other)", True),
    Line("life-insurance-loans", "Loans against life insurance", True),
    Line("mortgages", "Mortgages on real estate", True),
    Line("unpaid-taxes", "Unpaid taxes", True),
    Line("other-liabilities", "Other liabilities", True),
)
LINES = {line.key: line for line in ASSET_LINES + LIABILITY_LINES}
# The lines whose assets are in the real estate and vehicles schedule.
PROPERTY_LINES = ("real-estate", "automobiles")


def _names(*patterns: str) -> re.Pattern[str]:
    """Account names with a component starting with one of the patterns, ignoring case."""
    return re.compile(rf"(^|:)({'|'.join(patterns)})", re.IGNORECASE)


# Name patterns, matched at the start of an account name's component: e.g.
# Assets:Vanguard:RothIRA isn't "IRA", but Roth is retirement.
SAVINGS_NAMES = _names("savings", "moneymarket", "money-market", "cds?(:|$)")
RETIREMENT_NAMES = _names(
    "retirement", "401k", "403b", "457", "roth", "pension", "tsp(:|$)", "ira(:|$)"
)
RECEIVABLE_NAMES = _names("receivable", "loanedout", "notesreceivable")
LIFE_INSURANCE_NAMES = _names("lifeinsurance", "life-insurance", "cashvalue")
# "Car" but not "Card".
VEHICLE_NAMES = _names("car(?!d)", "auto", "vehicle", "truck", "motorcycle", "boat", "rv(:|$)")
REAL_ESTATE_NAMES = _names(
    "home", "house", "condo", "realestate", "real-estate", "property", "land", "rental", "cabin"
)
MORTGAGE_NAMES = _names("mortgage", "heloc", r"\w*mortgage")
CARD_NAMES = _names(r"\w*card", "amex", "visa", "mastercard", "discover")
TAX_NAMES = _names(r"\w*tax")
INSTALLMENT_NAMES = _names("student", "personal", "installment")
LOAN_NAMES = _names(r"\w*loan", r"\w*note")


def last4(number: object) -> str | None:
    """The last 4 digits of an account number, or None without digits."""
    digits = re.sub(r"\D", "", str(number))
    return digits[-4:] if digits else None


def label(account: str) -> str:
    """An account's name for a reader, without its root: e.g. ``Bank › Checking``."""
    return " › ".join(account_lib.split(account)[1:]) or account


def subtract(left: Mapping[str, Decimal], right: Mapping[str, Decimal]) -> Amounts:
    """``left`` minus ``right``, per currency."""
    found: dict[str, Decimal] = defaultdict(Decimal, left)
    for currency, number in right.items():
        found[currency] -= number
    return dict(found)


def _add(totals: dict[str, Decimal], values: Mapping[str, Decimal]) -> None:
    for currency, number in values.items():
        totals[currency] = totals.get(currency, Decimal(0)) + number


@dataclass(frozen=True)
class Account:
    """An asset or liability account, as the summary shows it."""

    account: str
    line: Line
    reason: str  # why it's on its line
    opened: datetime.date
    number: str | None = None  # the last 4 digits
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
        return subtract({}, self.value) if self.line.liability else self.value


@dataclass
class Payments:
    """An account's payments: the transactions adding to it, e.g. an expense or a loan payment."""

    account: str
    last_paid: datetime.date | None = None
    last_amount: Amounts = field(default_factory=dict)
    paid_from: list[str] = field(default_factory=list)  # by the last payment
    count: int = 0  # in the last 12 months
    yearly: Amounts = field(default_factory=dict)  # in the last 12 months

    @property
    def paid_from_labels(self) -> str:
        return ", ".join(label(account) for account in self.paid_from)


@dataclass(frozen=True)
class Bill:
    """An account marked as a bill, by its name for the reader, and its payments."""

    name: str
    payments: Payments


@dataclass(frozen=True)
class Loan:
    """A loan against a property, and its payments."""

    account: Account
    payments: Payments


@dataclass(frozen=True)
class Property:
    """Real estate or a vehicle, the loans against it, and the equity in it."""

    asset: Account
    value: Amounts  # with its subaccounts'
    loans: list[Loan]

    @property
    def owed(self) -> Amounts:
        found: dict[str, Decimal] = {}
        for loan in self.loans:
            _add(found, loan.account.amount)
        return found

    @property
    def equity(self) -> Amounts:
        return subtract(self.value, self.owed)


def _inherited(meta: Mapping[str, Mapping[str, object]], account: str, key: str) -> object:
    """A metadata value on the account's ``open`` directive, or its nearest parent's."""
    for name in account_lib.parents(account):
        if key in meta.get(name, {}):
            return meta[name][key]
    return None


def _declared(
    meta: Mapping[str, Mapping[str, object]], account: str, liability: bool
) -> tuple[Line, str] | None:
    """The line declared with ``asset-type`` or ``liability-type``, on the account or its
    nearest parent."""
    meta_key = LIABILITY_TYPE_KEY if liability else ASSET_TYPE_KEY
    for name in account_lib.parents(account):
        key = meta.get(name, {}).get(meta_key)
        if key in LINES and LINES[str(key)].liability == liability:
            where = "" if name == account else f" on {name}"
            return LINES[str(key)], f"{meta_key}: {key}{where}"
    return None


def commodity_lines(entries: Iterable[Directive]) -> dict[str, Line]:
    """The asset lines declared on commodities with ``asset-type``, e.g. a property's."""
    return {
        entry.currency: LINES[str(entry.meta[ASSET_TYPE_KEY])]
        for entry in entries
        if isinstance(entry, Commodity)
        and entry.meta.get(ASSET_TYPE_KEY) in LINES
        and not LINES[str(entry.meta[ASSET_TYPE_KEY])].liability
    }


def _held_line(currencies: Iterable[str], lines: Mapping[str, Line]) -> tuple[Line, str] | None:
    """The line of the commodities an account holds, if they declare one, and the same one."""
    declared = {currency: lines[currency] for currency in currencies if currency in lines}
    if len(set(declared.values())) == 1:
        currency, line = next(iter(declared.items()))
        return line, f"{ASSET_TYPE_KEY}: {line.key} on commodity {currency}"
    return None


def asset_line(
    account: str,
    role: Role,
    meta: Mapping[str, Mapping[str, object]],
    loans: Sequence[str],
    held: tuple[Line, str] | None = None,
) -> tuple[Line, str]:
    """An asset's line, and why: declared, or else inferred.

    In order: ``asset-type`` on the account or a parent; ``asset-type`` on the
    commodities it holds (``held``, from `commodity_lines`); a retirement account
    by name (e.g. 401k, IRA, Roth, Pension), even if cash; the ``cash`` role
    (savings if named Savings, Money Market or CD, else cash); its name
    (receivables, life insurance, a vehicle, real estate); a mortgage or vehicle
    loan opened under its path (``loans``); and otherwise stocks and bonds.
    """
    declared = _declared(meta, account, liability=False) or held
    if declared:
        return declared
    # Retirement first: cash in a retirement account is still retirement savings.
    if RETIREMENT_NAMES.search(account):
        return LINES["retirement"], "by its name"
    if role.role == CASH:
        if SAVINGS_NAMES.search(account):
            return LINES["savings"], "cash, named as savings"
        return LINES["cash"], "cash"
    for names, key in (
        (RECEIVABLE_NAMES, "receivables"),
        (LIFE_INSURANCE_NAMES, "life-insurance"),
        (VEHICLE_NAMES, "automobiles"),
        (REAL_ESTATE_NAMES, "real-estate"),
    ):
        if names.search(account):
            return LINES[key], "by its name"
    for loan in loans:
        if MORTGAGE_NAMES.search(loan):
            return LINES["real-estate"], f"secures {loan}"
        if VEHICLE_NAMES.search(loan):
            return LINES["automobiles"], f"secures {loan}"
    return LINES["stocks-bonds"], "an investment, by default"


def liability_line(
    account: str, meta: Mapping[str, Mapping[str, object]], secures: Line | None
) -> tuple[Line, str]:
    """A liability's line, and why: declared, or else inferred.

    In order: ``liability-type`` on the account or a parent; its name (a mortgage or HELOC, a
    card, taxes, a life insurance loan, a vehicle loan, a student, personal or
    installment loan); the line of the asset it's opened under (``secures``:
    real estate's is a mortgage, a vehicle's an auto loan); a loan or note by
    name (notes payable); and otherwise other liabilities.
    """
    declared = _declared(meta, account, liability=True)
    if declared:
        return declared
    for names, key in (
        (MORTGAGE_NAMES, "mortgages"),
        (CARD_NAMES, "credit-cards"),
        (TAX_NAMES, "unpaid-taxes"),
        (LIFE_INSURANCE_NAMES, "life-insurance-loans"),
        (VEHICLE_NAMES, "auto-loans"),
        (INSTALLMENT_NAMES, "installment-loans"),
    ):
        if names.search(account):
            return LINES[key], "by its name"
    if secures and secures.key == "real-estate":
        return LINES["mortgages"], "secured by real estate"
    if secures and secures.key == "automobiles":
        return LINES["auto-loans"], "secured by a vehicle"
    if LOAN_NAMES.search(account):
        return LINES["notes-payable"], "by its name"
    return LINES["other-liabilities"], "by default"


def _matching_path(account: str, root: str) -> str:
    """The account's path under another root, e.g. Liabilities:Home for Assets:Home."""
    return account_lib.join(root, *account_lib.split(account)[1:])


def lines(
    entries: Iterable[Directive], roles: Mapping[str, Role], account_types: AccountTypes
) -> dict[str, tuple[Line, str]]:
    """Each opened asset and liability account's line, and why (see `asset_line` and
    `liability_line`)."""
    entries = list(entries)
    opens = [entry for entry in entries if isinstance(entry, Open)]
    meta = {entry.account: entry.meta for entry in opens}
    liabilities = [name for name in meta if get_account_type(name) == account_types.liabilities]
    declared_commodities = commodity_lines(entries)
    held: dict[str, set[str]] = defaultdict(set)
    for txn in entries:
        if isinstance(txn, Transaction):
            for posting in txn.postings:
                held[posting.account].add(posting.units.currency)
    found: dict[str, tuple[Line, str]] = {}
    # Assets first: a liability's line can depend on the asset it's opened under.
    for name in sorted(meta, key=lambda name: get_account_type(name) != account_types.assets):
        root = get_account_type(name)
        if root == account_types.assets:
            path = _matching_path(name, account_types.liabilities)
            loans = [loan for loan in liabilities if loan == path or loan.startswith(path + ":")]
            held_line = _held_line(held[name], declared_commodities)
            found[name] = asset_line(name, roles[name], meta, loans, held_line)
        elif root == account_types.liabilities:
            secured = [
                found[parent][0]
                for parent in account_lib.parents(_matching_path(name, account_types.assets))
                if parent in found
            ]
            found[name] = liability_line(name, meta, secured[0] if secured else None)
    return found


def accounts(
    entries: Iterable[Directive],
    roles: Mapping[str, Role],
    account_types: AccountTypes,
    values: Mapping[str, Amounts],
) -> tuple[list[Account], list[Account]]:
    """The open and the closed asset and liability accounts, by line and institution.

    ``values`` are the accounts' values, e.g. from `values_by_account`. A parent
    of other accounts, e.g. one opened only to give them an institution, is left
    out unless it holds something itself.
    """
    entries = list(entries)
    closed = {entry.account: entry.date for entry in entries if isinstance(entry, Close)}
    opens = [entry for entry in entries if isinstance(entry, Open)]
    meta = {entry.account: entry.meta for entry in opens}
    parents = {parent for name in meta for parent in account_lib.parents(name) if parent != name}
    placed = lines(entries, roles, account_types)
    found = []
    for entry in opens:
        name = entry.account
        if name not in placed or (name in parents and not any(values.get(name, {}).values())):
            continue
        line, reason = placed[name]
        number = entry.meta.get(ACCOUNT_NUMBER_KEY)
        institution, owner = (_inherited(meta, name, key) for key in (INSTITUTION_KEY, OWNER_KEY))
        found.append(
            Account(
                name,
                line,
                reason,
                entry.date,
                last4(number) if number is not None else None,
                str(institution) if institution is not None else None,
                str(owner) if owner is not None else None,
                values.get(name, {}),
                closed.get(name),
            )
        )
    order = list(LINES)
    found.sort(
        key=lambda item: (
            order.index(item.line.key),
            (item.institution or "").lower(),
            item.account,
        )
    )
    return [item for item in found if not item.closed], [item for item in found if item.closed]


def payments(
    entries: Iterable[Directive],
    names: Iterable[str],
    account_types: AccountTypes,
    today: datetime.date,
) -> dict[str, Payments]:
    """Each account's payments: the transactions adding to it, e.g. an expense or a loan payment.

    A payment's amount is what left the accounts that paid it: the asset and
    liability accounts it took money from.
    """
    found = {name: Payments(name) for name in names}
    held = (account_types.assets, account_types.liabilities)
    for txn in entries:
        if not isinstance(txn, Transaction) or txn.date > today:
            continue
        for name in {p.account for p in txn.postings if p.account in found and p.units.number > 0}:
            payment = found[name]
            paid: dict[str, Decimal] = defaultdict(Decimal)
            sources = []
            for posting in txn.postings:
                weight = convert.get_weight(posting)
                funds = posting.account != name and get_account_type(posting.account) in held
                if funds and weight.number < 0:
                    paid[weight.currency] -= weight.number
                    sources.append(posting.account)
            payment.last_paid = txn.date
            payment.last_amount = dict(paid)
            payment.paid_from = sources
            if txn.date > today - ONE_YEAR:
                payment.count += 1
                _add(payment.yearly, paid)
    return found


def bills(
    entries: Iterable[Directive], account_types: AccountTypes, today: datetime.date
) -> list[Bill]:
    """The accounts marked ``bill``, with their payments, by name."""
    entries = list(entries)
    marked = {}
    for entry in entries:
        if isinstance(entry, Open) and entry.meta.get(BILL_KEY, False) is not False:
            name = entry.meta[BILL_KEY]
            marked[entry.account] = name if isinstance(name, str) else label(entry.account)
    found = payments(entries, marked, account_types, today)
    return sorted(
        (Bill(name, found[account]) for account, name in marked.items()),
        key=lambda bill: bill.name.lower(),
    )


def properties(
    open_accounts: Sequence[Account],
    totals: Mapping[str, Amounts],
    loan_payments: Mapping[str, Payments],
    account_types: AccountTypes,
) -> list[Property]:
    """The real estate and vehicles, with the loans opened under their matching path."""
    found = []
    for item in open_accounts:
        if item.line.key not in PROPERTY_LINES:
            continue
        path = _matching_path(item.account, account_types.liabilities)
        loans = [
            Loan(loan, loan_payments[loan.account])
            for loan in open_accounts
            if loan.line.liability and (loan.account == path or loan.account.startswith(path + ":"))
        ]
        found.append(Property(item, totals.get(item.account, item.value), loans))
    return found


@dataclass(frozen=True)
class Summary:
    """Everything the summary shows, as of a date."""

    title: str
    date: datetime.date
    currency: str | None
    open_accounts: list[Account]
    closed_accounts: list[Account]
    properties: list[Property]
    bills: list[Bill]

    def lines(self, liability: bool) -> list[tuple[Line, list[Account], Amounts]]:
        """The asset or liability lines with open accounts, their accounts and total."""
        found = []
        for line in LIABILITY_LINES if liability else ASSET_LINES:
            items = [item for item in self.open_accounts if item.line == line]
            if items:
                total: dict[str, Decimal] = {}
                for item in items:
                    _add(total, item.amount)
                found.append((line, items, total))
        return found

    @property
    def assets(self) -> Amounts:
        total: dict[str, Decimal] = {}
        for _, _, line_total in self.lines(liability=False):
            _add(total, line_total)
        return total

    @property
    def debts(self) -> Amounts:
        """What's owed: positive."""
        total: dict[str, Decimal] = {}
        for _, _, line_total in self.lines(liability=True):
            _add(total, line_total)
        return total

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
            _add(totals[name], value)
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
    loans = [item.account for item in open_accounts if item.line.liability]
    return Summary(
        str(options["title"]),
        date,
        currency,
        open_accounts,
        closed_accounts,
        properties(
            open_accounts, totals, payments(entries, loans, account_types, date), account_types
        ),
        bills(entries, account_types, date),
    )
