"""Values of postings and holdings in one currency, for the Fava reports.

Beancount's conversion functions return an amount they can't convert (for lack
of a price) unchanged, in its own currency. A report that adds values up in one
currency has to catch those, or it adds numbers in different currencies. These
do that, leave such amounts out and collect their currencies for the report to
show. Holdings without a market price yet are valued at cost.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal

from beancount.core import convert, prices
from beancount.core.data import Posting
from beancount.core.inventory import Inventory


def posting_value(
    posting: Posting,
    currency: str,
    price_map: prices.PriceMap,
    date: datetime.date,
    unconverted: set[str],
) -> Decimal:
    """A posting's weight in ``currency`` on the date, or 0 if it can't be converted.

    The weight is what the posting balances against: its cost or price if it has
    one, else its units. A currency that can't be converted is added to
    ``unconverted``.
    """
    amount = convert.convert_amount(convert.get_weight(posting), currency, price_map, date)
    if amount.currency != currency:
        unconverted.add(amount.currency)
        return Decimal(0)
    return amount.number


def market_values(
    balances: Mapping[str, Inventory],
    currency: str,
    price_map: prices.PriceMap,
    date: datetime.date,
    unconverted: set[str],
) -> dict[str, Decimal]:
    """Each account's market value in ``currency`` on the date, or its cost without a price.

    Positions that can't be converted are left out, and their currencies added to
    ``unconverted``.
    """
    values: dict[str, Decimal] = defaultdict(Decimal)
    for account, inventory in balances.items():
        for position in inventory:
            amount = convert.convert_position(position, currency, price_map, date)
            if amount.currency != currency and position.cost:
                # No market price yet: value it at cost.
                cost = convert.get_cost(position)
                amount = convert.convert_amount(cost, currency, price_map, date)
            if amount.currency != currency:
                unconverted.add(amount.currency)
                continue
            values[account] += amount.number
    return values
