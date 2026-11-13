"""Concise constructors for Beancount directives.

Beancount's directive types are named tuples whose fields must all be given
explicitly. These builders fill in sensible defaults so entries can be built
tersely, e.g. in importers, plugins and tests::

    T(
        "2020-02-01",
        narration="Lunch",
        postings=[P("Assets:Cash", A("-10", "USD")), P("Expenses:Food", A(10, "USD"))],
    )

Dates may be given as ``datetime.date`` objects or ISO ``YYYY-MM-DD`` strings.
Every call gets its own fresh metadata dict, tag/link sets and posting list.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from decimal import Decimal

from beancount.core.amount import Amount
from beancount.core.data import Balance, Cost, CostSpec, Meta, Posting, Transaction
from beancount.core.flags import FLAG_OKAY
from beancount.core.number import D

DateLike = datetime.date | str


def A(number: Decimal | int | str, currency: str) -> Amount:
    """Build an Amount. Floats are rejected, since they can't be represented exactly."""
    if isinstance(number, float):
        raise TypeError(f"use a str, int or Decimal for amounts, not float: {number!r}")
    return Amount(D(number), currency)


def T(
    date: DateLike,
    *,
    flag: str = FLAG_OKAY,
    payee: str | None = None,
    narration: str = "",
    tags: Iterable[str] = (),
    links: Iterable[str] = (),
    postings: Iterable[Posting] = (),
    meta: Meta | None = None,
) -> Transaction:
    """Build a Transaction."""
    return Transaction(
        meta=dict(meta or {}),
        date=_to_date(date),
        flag=flag,
        payee=payee,
        narration=narration,
        tags=frozenset(tags),
        links=frozenset(links),
        postings=list(postings),
    )


def P(
    account: str,
    units: Amount | None = None,
    *,
    cost: Cost | CostSpec | None = None,
    price: Amount | None = None,
    flag: str | None = None,
    meta: Meta | None = None,
) -> Posting:
    """Build a Posting. Omit ``units`` to leave the amount for Beancount to infer."""
    return Posting(
        account=account,
        units=units,
        cost=cost,
        price=price,
        flag=flag,
        meta=dict(meta or {}),
    )


def B(
    date: DateLike,
    account: str,
    amount: Amount,
    *,
    tolerance: Decimal | None = None,
    diff_amount: Amount | None = None,
    meta: Meta | None = None,
) -> Balance:
    """Build a Balance assertion."""
    return Balance(
        meta=dict(meta or {}),
        date=_to_date(date),
        account=account,
        amount=amount,
        tolerance=tolerance,
        diff_amount=diff_amount,
    )


def _to_date(value: DateLike) -> datetime.date:
    if isinstance(value, datetime.datetime):
        raise TypeError(f"expected a date, not a datetime: {value!r}")
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(value)
