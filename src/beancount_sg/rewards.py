"""Credit card rewards: spending per card and category, and the rewards it earns.

Configure a card's rewards with metadata on its ``open`` directive:

    2020-01-01 open Liabilities:CreditCard:Sapphire USD
      rewards: "points"            ; or "cashback"
      rewards-rate: 1              ; the default rate, for categories without their own
      rewards-rate-dining: 3       ; a category's rate
      rewards-rate-travel: 2
      rewards-unit: "UR"           ; points only: what the points are called
      rewards-point-value: 0.0125  ; points only, optional: a point's value in cash

Rates are written the same way for both kinds of rewards: for ``cashback`` a rate
of 3 means 3% back, in the currency spent; for ``points`` it means 3 points per
unit spent. ``rewards-rate`` defaults to 1; ``rewards-unit`` to ``points``.

Spending is a card's charges to expenses: the ``Expenses`` postings of each
transaction that posts to the card (or one of its subaccounts). Refunds count
negatively. A posting's *category* is its ``category`` metadata, or else its
transaction's; spending without one is ``uncategorized`` and earns the default
rate. A category's rate key is the category slugified, e.g. ``Food and Drink``
uses ``rewards-rate-food-and-drink``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from beancount.core import account as account_lib
from beancount.core.account_types import DEFAULT_ACCOUNT_TYPES, AccountTypes, get_account_type
from beancount.core.amount import Amount
from beancount.core.data import Directive, Meta, Open, Transaction
from slugify import slugify

CASHBACK = "cashback"
POINTS = "points"
UNCATEGORIZED = "uncategorized"
META_PREFIX = "rewards"


class RewardsError(NamedTuple):
    """Conforms to `beancount.core.data.BeancountError`."""

    source: Meta
    message: str
    entry: Directive


@dataclass(frozen=True)
class Program:
    """A card's rewards program, from its ``open`` metadata."""

    account: str
    kind: str  # CASHBACK or POINTS
    default_rate: Decimal = Decimal(1)
    rates: dict[str, Decimal] = field(default_factory=dict)  # slugified category -> rate
    unit: str = POINTS
    point_value: Decimal | None = None

    def rate(self, category: str) -> Decimal:
        """The rate for a category, or the default rate."""
        return self.rates.get(slugify(category), self.default_rate)

    def reward(self, spend: Amount, category: str) -> Amount:
        """What ``spend`` in ``category`` earns: cash for cashback, else points."""
        rate = self.rate(category)
        if self.kind == CASHBACK:
            return Amount(spend.number * rate / 100, spend.currency)
        return Amount(spend.number * rate, self.unit)

    def value(self, reward: Amount, currency: str) -> Amount | None:
        """A reward's cash value: itself for cashback, or points at their point value."""
        if self.kind == CASHBACK:
            return reward
        if self.point_value is None:
            return None
        return Amount(reward.number * self.point_value, currency)


def programs(entries: Iterable[Directive]) -> tuple[dict[str, Program], list[RewardsError]]:
    """Each card's rewards program, by account, from ``open`` directives' metadata."""
    found: dict[str, Program] = {}
    errors: list[RewardsError] = []
    for entry in entries:
        if not isinstance(entry, Open) or META_PREFIX not in entry.meta:
            continue
        try:
            found[entry.account] = _program(entry)
        except ValueError as error:
            errors.append(RewardsError(entry.meta, f"{entry.account}: {error}", entry))
    return found, errors


def _program(entry: Open) -> Program:
    meta = entry.meta
    kind = meta[META_PREFIX]
    if kind not in (CASHBACK, POINTS):
        raise ValueError(f'{META_PREFIX} must be "{CASHBACK}" or "{POINTS}", not {kind!r}')
    rate_prefix = f"{META_PREFIX}-rate-"
    point_value = meta.get(f"{META_PREFIX}-point-value")
    return Program(
        account=entry.account,
        kind=kind,
        default_rate=_number(meta, f"{META_PREFIX}-rate", Decimal(1)),
        rates={
            key.removeprefix(rate_prefix): _number(meta, key)
            for key in meta
            if key.startswith(rate_prefix)
        },
        unit=str(meta.get(f"{META_PREFIX}-unit", POINTS)),
        point_value=None if point_value is None else _number(meta, f"{META_PREFIX}-point-value"),
    )


def _number(meta: Meta, key: str, default: Decimal | None = None) -> Decimal:
    value = meta.get(key, default)
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{key} must be a number, not {value!r}") from None


@dataclass(frozen=True)
class CategoryRewards:
    """Spending on a card in one category and currency, and what it earned."""

    program: Program
    category: str
    spend: Amount

    @property
    def rate(self) -> Decimal:
        return self.program.rate(self.category)

    @property
    def reward(self) -> Amount:
        return self.program.reward(self.spend, self.category)

    @property
    def value(self) -> Amount | None:
        return self.program.value(self.reward, self.spend.currency)


def category_rewards(
    entries: Iterable[Directive],
    cards: dict[str, Program],
    account_types: AccountTypes = DEFAULT_ACCOUNT_TYPES,
) -> list[CategoryRewards]:
    """Spending and rewards per card, category and currency, sorted by card then category.

    A transaction posting to more than one rewards card is skipped, since its
    spending can't be attributed to one of them.
    """
    matchers = {account: account_lib.parent_matcher(account) for account in cards}
    spend: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    for txn in entries:
        if not isinstance(txn, Transaction):
            continue
        charged = {
            card
            for card, matches in matchers.items()
            for posting in txn.postings
            if matches(posting.account)
        }
        if len(charged) != 1:
            continue
        [card] = charged
        for posting in txn.postings:
            if get_account_type(posting.account) != account_types.expenses:
                continue
            category = (posting.meta or {}).get("category") or txn.meta.get("category")
            key = (card, str(category or UNCATEGORIZED), posting.units.currency)
            spend[key] += posting.units.number
    return [
        CategoryRewards(cards[card], category, Amount(number, currency))
        for (card, category, currency), number in sorted(spend.items())
    ]
