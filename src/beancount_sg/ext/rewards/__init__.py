"""A Fava report of credit card rewards: spending per card and category, and rewards.

Enable it in the ledger, and configure cards' rewards on their ``open``
directives (see `beancount_sg.rewards`):

    2020-01-01 custom "fava-extension" "beancount_sg.ext.rewards"

The "Credit Card Rewards" report covers the transactions in the current Fava
filter. It has a table per card (spend, rate, reward and, where known, cash
value per category) and hierarchy charts (treemap, sunburst or icicle) of the
spend and the rewards' cash value by card and category, so cashback and points
cards can be compared. Points without a ``rewards-point-value`` have no cash
value, so they're left out of the value chart.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from beancount.core import account as account_lib
from beancount.core.amount import Amount
from beancount.parser.options import get_account_types
from fava.context import g
from fava.core.inventory import SimpleCounterInventory
from fava.core.tree import SerialisedTreeNode
from fava.ext import FavaExtensionBase
from fava.internal_api import HierarchyChart

from beancount_sg.rewards import (
    CASHBACK,
    CategoryRewards,
    Program,
    RewardsError,
    category_rewards,
    programs,
)


@dataclass(frozen=True)
class CardRewards:
    """A card's program, its rows per category, and their totals."""

    program: Program
    rows: list[CategoryRewards]

    @property
    def spend(self) -> list[Amount]:
        return _totals(row.spend for row in self.rows)

    @property
    def reward(self) -> list[Amount]:
        return _totals(row.reward for row in self.rows)

    @property
    def value(self) -> list[Amount]:
        return _totals(row.value for row in self.rows if row.value is not None)

    def rate_label(self, rate: Decimal) -> str:
        """A rate as shown in the table, e.g. ``3%`` cashback or ``3x`` points."""
        return f"{rate}%" if self.program.kind == CASHBACK else f"{rate}x"


class CreditCardRewards(FavaExtensionBase):
    """Fava report of credit card rewards by card and category."""

    report_title = "Credit Card Rewards"

    def _programs(self) -> tuple[dict[str, Program], list[RewardsError]]:
        # From all entries, so a card's configuration applies whatever the filter.
        return programs(self.ledger.all_entries_by_type.Open)

    def errors(self) -> list[RewardsError]:
        """Invalid rewards configurations."""
        return self._programs()[1]

    def cards(self) -> list[CardRewards]:
        """Each configured card's rewards, within the current Fava filter."""
        found, _ = self._programs()
        rows = category_rewards(g.filtered.entries, found, get_account_types(self.ledger.options))
        by_card: dict[str, list[CategoryRewards]] = defaultdict(list)
        for row in rows:
            by_card[row.program.account].append(row)
        return [CardRewards(found[account], by_card[account]) for account in sorted(found)]

    def charts(self) -> list[HierarchyChart]:
        """Hierarchy charts of spend and rewards' cash value by card, then category."""
        cards = self.cards()
        return [
            HierarchyChart("Spend", _tree(cards, lambda row: row.spend)),
            HierarchyChart("Value", _tree(cards, lambda row: row.value)),
        ]


def _totals(amounts: Iterable[Amount]) -> list[Amount]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for amount in amounts:
        totals[amount.currency] += amount.number
    return [Amount(number, currency) for currency, number in totals.items()]


def _tree(cards: list[CardRewards], amount_of) -> SerialisedTreeNode:
    """A chart tree: the cards' common parent account, each card, then its categories.

    The root is the common prefix of the cards' parents, so a single card still
    gets its own node under the root.

    Fava's charts label nodes by their last account component, so a category's
    node is named ``<card>:<category>``.
    """
    root = account_lib.commonprefix(account_lib.parent(card.program.account) for card in cards)
    children = []
    for card in cards:
        leaves = [
            _node(f"{card.program.account}:{row.category.replace(':', '-')}", amount)
            for row in card.rows
            if (amount := amount_of(row)) is not None
        ]
        children.append(_parent(card.program.account, leaves))
    return _parent(root, children)


def _node(account: str, amount: Amount) -> SerialisedTreeNode:
    balance = SimpleCounterInventory({amount.currency: amount.number})
    return SerialisedTreeNode(account, balance, balance, [], has_txns=True)


def _parent(account: str, children: list[SerialisedTreeNode]) -> SerialisedTreeNode:
    total = SimpleCounterInventory()
    for child in children:
        for currency, number in child.balance_children.items():
            total[currency] = total.get(currency, Decimal(0)) + number
    return SerialisedTreeNode(account, SimpleCounterInventory(), total, children, has_txns=False)
