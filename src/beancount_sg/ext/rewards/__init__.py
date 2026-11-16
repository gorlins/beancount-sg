"""A Fava report of credit card rewards: spending per card and category, and rewards.

Enable it in the ledger, and configure cards' rewards on their ``open``
directives (see `beancount_sg.rewards`):

    2020-01-01 custom "fava-extension" "beancount_sg.ext.rewards"

Only expense postings count as spending, so payments from an ``Assets`` account
never do. If card payments are booked to an expense account instead, they'd look
like refunds; list such accounts (each with its subaccounts) in the extension's
config to leave them out:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.rewards" "{
      'exclude_accounts': ['Expenses:LoanPayments:CreditCardPayment'],
    }"

The "Credit Card Rewards" report covers the transactions in the current Fava
filter. Its table has a row per card and category: the rate, spend, reward and,
where known, the reward's cash value. Its hierarchy charts (e.g. as an icicle)
show the spend and the rewards' cash value by card, then category, so cashback
and points cards can be compared. Points without a ``rewards-point-value`` have
no cash value, so they're left out of the value chart.

A category, in the table or the charts, links to the card's account page
filtered to that category's transactions (by its category metadata, on the
transaction or any posting).

Fava's charts label nodes by their last account component and link them to
account pages, so a category's node is named ``<card>:<category>``; the page's
script (``CreditCardRewards.js``) points those links at the category's filter
instead.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core.amount import Amount
from beancount.parser.options import get_account_types
from fava.context import g
from fava.core.inventory import SimpleCounterInventory
from fava.core.tree import SerialisedTreeNode
from fava.ext import FavaExtensionBase
from fava.internal_api import HierarchyChart
from flask import request, url_for

from beancount_sg.rewards import (
    CASHBACK,
    UNCATEGORIZED,
    CategoryRewards,
    Program,
    RewardsError,
    category_rewards,
    programs,
)

# The extension config's keys.
EXCLUDE_ACCOUNTS = "exclude_accounts"
CONFIG_EXAMPLE = f"{{'{EXCLUDE_ACCOUNTS}': ['Expenses:LoanPayments:CreditCardPayment']}}"


def excluded_accounts(config: object) -> list[str]:
    """The accounts that aren't spending, from the extension's config.

    Raises:
        ValueError: If the config isn't a dict with a list of account names.
    """
    if not config:
        return []
    if not isinstance(config, dict) or set(config) - {EXCLUDE_ACCOUNTS}:
        raise ValueError(f"the extension's config must be like {CONFIG_EXAMPLE}, not {config!r}")
    accounts = config.get(EXCLUDE_ACCOUNTS, [])
    if not isinstance(accounts, list | tuple) or not all(
        isinstance(account, str) and account_lib.is_valid(account) for account in accounts
    ):
        raise ValueError(f"{EXCLUDE_ACCOUNTS} must be a list of account names, not {accounts!r}")
    return list(accounts)


class CreditCardRewards(FavaExtensionBase):
    """Fava report of credit card rewards by card and category."""

    report_title = "Credit Card Rewards"
    has_js_module = True

    def _programs(self) -> tuple[dict[str, Program], list[RewardsError]]:
        # From all entries, so a card's configuration applies whatever the filter.
        return programs(self.ledger.all_entries_by_type.Open)

    def errors(self) -> list[str]:
        """Problems with the extension's config or cards' rewards configurations."""
        messages = [error.message for error in self._programs()[1]]
        try:
            excluded_accounts(self.config)
        except ValueError as error:
            messages.insert(0, f"Credit Card Rewards: {error}")
        return messages

    def configured(self) -> bool:
        """Whether any card has rewards configured."""
        return bool(self._programs()[0])

    def _excluded(self) -> list[str]:
        # An invalid config excludes nothing; errors() reports it.
        try:
            return excluded_accounts(self.config)
        except ValueError:
            return []

    def rows(self) -> list[CategoryRewards]:
        """Spending and rewards per card and category, within the current Fava filter."""
        found, _ = self._programs()
        return category_rewards(
            g.filtered.entries,
            found,
            get_account_types(self.ledger.options),
            excluded=self._excluded(),
        )

    @staticmethod
    def totals(amounts: Iterable[Amount | None]) -> list[Amount]:
        """The amounts' totals, one per currency."""
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for amount in amounts:
            if amount:
                totals[amount.currency] += amount.number
        return [Amount(number, currency) for currency, number in totals.items()]

    @staticmethod
    def rate_label(row: CategoryRewards) -> str:
        """A row's rate as shown in the table, e.g. ``3%`` cashback or ``3x`` points."""
        return f"{row.rate}%" if row.program.kind == CASHBACK else f"{row.rate}x"

    def category_url(self, row: CategoryRewards) -> str:
        """The card's account page, filtered to the row's category.

        The category filter is added to the page's current filter, if any.
        """
        category_filter = _category_filter(
            row.program.category_key,
            row.category,
            get_account_types(self.ledger.options).expenses,
            self._excluded(),
        )
        current = request.args.get("filter")
        return url_for(
            "account",
            name=row.program.account,
            filter=f"({current}) ({category_filter})" if current else category_filter,
        )

    def category_links(self, rows: list[CategoryRewards]) -> dict[str, str]:
        """Each category chart node's account name, and the URL it should link to."""
        return {_node_account(row): self.category_url(row) for row in rows}

    @staticmethod
    def charts(rows: list[CategoryRewards]) -> list[HierarchyChart]:
        """Hierarchy charts of spend and rewards' cash value by card, then category."""
        return [
            HierarchyChart("Spend", _tree(rows, lambda row: row.spend)),
            HierarchyChart("Value", _tree(rows, lambda row: row.value)),
        ]


def _category_filter(key: str, category: str, expenses: str, excluded: list[str]) -> str:
    """A Fava filter for transactions with spending in a category.

    As in `beancount_sg.rewards.category_rewards`, an expense posting's category is
    its own ``key`` metadata, or else its transaction's. So a transaction is in a
    category if it has an expense posting with that category, or has the category
    itself and an expense posting without one. Uncategorized spending has the key
    on neither.
    """
    # Spending accounts: the expenses root and its subaccounts, but not excluded ones.
    not_excluded = "".join(f"(?!{re.escape(account)}(:|$))" for account in excluded)
    expense = f'account:"^{not_excluded}{re.escape(expenses)}(:|$)"'
    if category == UNCATEGORIZED:
        return f'-{key}:"" any({expense} -{key}:"")'
    # Fava matches values as case-insensitive regexes; \x22 is a quote, which
    # would otherwise end the filter's string.
    pattern = "^" + re.escape(category).replace('"', r"\x22") + "$"
    return f'{key}:"{pattern}" any({expense} -{key}:""), any({expense} {key}:"{pattern}")'


def _node_account(row: CategoryRewards) -> str:
    """The chart node's name for a row: ``<card>:<category>``."""
    return f"{row.program.account}:{row.category.replace(':', '-')}"


def _tree(
    rows: list[CategoryRewards], amount_of: Callable[[CategoryRewards], Amount | None]
) -> SerialisedTreeNode:
    """A chart tree: the cards' common parent account, each card, then its categories.

    The root is the common prefix of the cards' parents, so a single card still
    gets its own node under the root.
    """
    by_card: dict[str, list[SerialisedTreeNode]] = defaultdict(list)
    for row in rows:
        amount = amount_of(row)
        if amount:
            by_card[row.program.account].append(_node(_node_account(row), amount))
    root = account_lib.commonprefix(account_lib.parent(card) for card in by_card)
    return _parent(root, [_parent(card, leaves) for card, leaves in sorted(by_card.items())])


def _node(account: str, amount: Amount) -> SerialisedTreeNode:
    balance = SimpleCounterInventory({amount.currency: amount.number})
    return SerialisedTreeNode(account, balance, balance, [], has_txns=True)


def _parent(account: str, children: list[SerialisedTreeNode]) -> SerialisedTreeNode:
    total = SimpleCounterInventory()
    for child in children:
        for currency, number in child.balance_children.items():
            total[currency] = total.get(currency, Decimal(0)) + number
    return SerialisedTreeNode(account, SimpleCounterInventory(), total, children, has_txns=False)
