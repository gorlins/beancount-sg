"""Accounts' cash-flow roles, from ``cash-flow-role`` metadata or their names.

A convention for classifying accounts in cash-flow terms, shared with
Beancount.io's cash-flow report: declare an account's role on its ``open``
directive.

    2020-01-01 open Assets:US:Brokerage
      cash-flow-role: "investing"

The roles are ``cash`` (cash and equivalents), ``operating``, ``investing`` and
``financing``. An account without a declaration takes its nearest parent's (an
addition to that convention), or else the convention's default:

- Assets: ``cash`` if the name contains Cash, Checking, Savings or Bank, else
  ``investing``.
- Liabilities and Equity: ``financing``.
- Income and Expenses: ``operating``, except (another addition) ``financing`` if
  the name says it's a debt payment: it contains Repayment, or Payment after
  Loan, Mortgage or Card, e.g. ``Expenses:CreditCardPayment`` or
  ``Expenses:Mortgage:Payment``. Such accounts carry payments on their way to a
  loan or card, so they take the debt's role. ``Expenses:Rent:Payment`` and
  ``Expenses:Mortgage:Interest`` stay ``operating``.

A declaration that isn't one of these roles (e.g. a typo) is reported as an
error and ignored, so the account resolves as if it weren't there.
"""

from __future__ import annotations

import re
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from beancount.core import account as account_lib
from beancount.core.account_types import AccountTypes, get_account_type
from beancount.core.data import Directive, Meta, Open

ROLE_KEY = "cash-flow-role"
CASH, OPERATING, INVESTING, FINANCING = "cash", "operating", "investing", "financing"
ROLES = (CASH, OPERATING, INVESTING, FINANCING)
# Names of asset accounts that default to cash.
CASH_NAMES = re.compile(r"cash|checking|savings|bank", re.IGNORECASE)
# Names of income and expense accounts that carry debt payments, financing by default.
DEBT_PAYMENT_NAMES = re.compile(r"repayment|(loan|mortgage|card).*payment", re.IGNORECASE)


class RoleError(NamedTuple):
    """Conforms to `beancount.core.data.BeancountError`."""

    source: Meta
    message: str
    entry: Directive


@dataclass(frozen=True)
class Role:
    """An account's cash-flow role, and the account that declared it, if any."""

    role: str
    declared_by: str | None = None  # None when it's the default for the account's name

    @property
    def declared(self) -> bool:
        return self.declared_by is not None


def account_roles(
    entries: Iterable[Directive], account_types: AccountTypes
) -> tuple[dict[str, Role], list[RoleError]]:
    """Every opened account's role: declared, inherited from a parent, or the default.

    All declarations are read before any role is resolved, so an account inherits
    its parent's declaration whatever order they're opened in.
    """
    opens = [entry for entry in entries if isinstance(entry, Open)]
    declared, errors = _declarations(opens)
    roles = {entry.account: _role(entry.account, declared, account_types) for entry in opens}
    return roles, errors


def _declarations(opens: list[Open]) -> tuple[dict[str, str], list[RoleError]]:
    """The roles declared on ``open`` directives, by account, and unknown roles."""
    declared: dict[str, str] = {}
    errors: list[RoleError] = []
    for entry in opens:
        value = entry.meta.get(ROLE_KEY)
        if value is None:
            continue
        if value in ROLES:
            declared[entry.account] = value
        else:
            message = (
                f"{entry.account}: {ROLE_KEY} {value!r} isn't one of {', '.join(ROLES)};"
                " it's ignored"
            )
            errors.append(RoleError(entry.meta, message, entry))
    return declared, errors


def _role(account: str, declared: dict[str, str], account_types: AccountTypes) -> Role:
    """The account's own declared role, or its nearest parent's, or else the default."""
    for name in account_lib.parents(account):
        if name in declared:
            return Role(declared[name], declared_by=name)
    return Role(default_role(account, account_types))


def default_role(account: str, account_types: AccountTypes) -> str:
    """The role of an account without a declaration, from its name and type."""
    root = get_account_type(account)
    if root == account_types.assets:
        return CASH if CASH_NAMES.search(account) else INVESTING
    if root in (account_types.liabilities, account_types.equity):
        return FINANCING
    return FINANCING if DEBT_PAYMENT_NAMES.search(account) else OPERATING


def notable_accounts(classified: Mapping[str, Hashable], depth: int = 2) -> list[str]:
    """The accounts worth listing from a classification, e.g. of roles, sorted.

    Those up to ``depth`` components deep (e.g. ``Assets:Bank``), and deeper ones
    classified differently from their nearest parent in ``classified``, or with
    none: the rest are classified as their parent, so listing them adds nothing.
    """
    found = []
    for account in sorted(classified):
        parent = next(
            (
                name
                for name in account_lib.parents(account)
                if name != account and name in classified
            ),
            None,
        )
        if (
            len(account_lib.split(account)) <= depth
            or parent is None
            or classified[parent] != classified[account]
        ):
            found.append(account)
    return found
