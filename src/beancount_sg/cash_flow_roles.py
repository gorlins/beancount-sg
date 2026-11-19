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
- Income and Expenses: ``operating``.

An unknown role is reported as an error, and the default used.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
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
    """Every opened account's role: declared, inherited from a parent, or the default."""
    opens = {entry.account: entry for entry in entries if isinstance(entry, Open)}
    declared: dict[str, str] = {}
    errors: list[RoleError] = []
    for account, entry in opens.items():
        value = entry.meta.get(ROLE_KEY)
        if value is None:
            continue
        if value in ROLES:
            declared[account] = value
        else:
            message = f"{account}: unknown {ROLE_KEY} {value!r}, using the default"
            errors.append(RoleError(entry.meta, message, entry))
    roles = {}
    for account in opens:
        declarer = next(
            (parent for parent in self_and_parents(account) if parent in declared), None
        )
        if declarer:
            roles[account] = Role(declared[declarer], declarer)
        else:
            roles[account] = Role(default_role(account, account_types))
    return roles, errors


def self_and_parents(account: str) -> Iterable[str]:
    """The account, then each of its parents, nearest first."""
    while account:
        yield account
        account = account_lib.parent(account)


def default_role(account: str, account_types: AccountTypes) -> str:
    """The role of an account without a declaration, from its name and type."""
    root = get_account_type(account)
    if root == account_types.assets:
        return CASH if CASH_NAMES.search(account) else INVESTING
    if root in (account_types.liabilities, account_types.equity):
        return FINANCING
    return OPERATING
