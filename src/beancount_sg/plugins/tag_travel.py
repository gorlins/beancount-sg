"""Tag travel spending, and everyday spending while away, with the trip.

Record where you are with ``travel`` events, and ``home`` when you get back:

    2024-03-04 event "travel" "New York City"
    2024-03-09 event "travel" "home"

Configure which accounts to tag, as a Python dict:

    plugin "beancount_sg.plugins.tag_travel" "{
      'travel_accounts': ['Expenses:Travel'],
      'conditional_accounts': ['Expenses:Food', 'Expenses:Transport'],
    }"

Then a transaction with a posting to (a subaccount of) one of these accounts
is tagged:

- ``travel_accounts``: always ``#travel``, plus the trip tag while away, so
  e.g. flights booked from home are still travel;
- ``conditional_accounts``: ``#travel`` and the trip tag, only while away.

The trip tag is the location and the year the trip started, e.g.
``#new-york-city-2024``, lowercased with accents and punctuation removed.

An event applies from its date onward, including transactions on that date,
until the next ``travel`` event. Before the first event you're at home.

Usage::

    plugin "beancount_sg.plugins.tag_travel" "{'travel_accounts': [...], ...}"
"""

from __future__ import annotations

import bisect
import datetime
import functools
import re
import unicodedata
from ast import literal_eval
from collections.abc import Callable, Sequence
from typing import Any

from beancount.core import account as account_lib
from beancount.core.data import Directive, Event, Transaction

from .plugin_helpers import map_transactions

__plugins__ = ("tag_travel",)

TAG = "travel"
EVENT_TYPE = "travel"
HOME = "home"

_CONFIG_KEYS = {"travel_accounts", "conditional_accounts"}


def tag_travel(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Tag transactions in the configured accounts with #travel and the current trip."""
    settings = _parse_config(config)
    travel = _matcher(settings.get("travel_accounts", []))
    conditional = _matcher(settings.get("conditional_accounts", []))
    dates, trips = trip_timeline(entries)
    return map_transactions(
        entries,
        functools.partial(
            tag_transaction, dates=dates, trips=trips, travel=travel, conditional=conditional
        ),
    )


def trip_timeline(entries: list[Directive]) -> tuple[list[datetime.date], list[str | None]]:
    """Parallel lists of travel event dates and the trip tag from each (None at home).

    Entries are in date order, and same-date events in file order, so the last
    event on a date wins.
    """
    dates: list[datetime.date] = []
    trips: list[str | None] = []
    for entry in entries:
        if isinstance(entry, Event) and entry.type == EVENT_TYPE:
            dates.append(entry.date)
            is_home = entry.description.strip().lower() == HOME
            trips.append(None if is_home else trip_tag(entry.description, entry.date))
    return dates, trips


def trip_tag(location: str, date: datetime.date) -> str:
    """A tag for a trip, e.g. ``new-york-city-2024`` for "New York City" in 2024."""
    ascii_text = unicodedata.normalize("NFKD", location).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return f"{slug}-{date.year}"


def tag_transaction(
    txn: Transaction,
    *,
    dates: list[datetime.date],
    trips: list[str | None],
    travel: Callable[[str], bool],
    conditional: Callable[[str], bool],
) -> Transaction:
    """The transaction with #travel and its trip tag added, if it should have them."""
    # The trip in effect on the transaction's date: from the last event on or before it.
    index = bisect.bisect_right(dates, txn.date) - 1
    trip = trips[index] if index >= 0 else None

    accounts = [posting.account for posting in txn.postings]
    is_travel = any(travel(account) for account in accounts)
    is_conditional = trip is not None and any(conditional(account) for account in accounts)
    if not (is_travel or is_conditional):
        return txn
    new_tags = {TAG} if trip is None else {TAG, trip}
    tags = txn.tags or frozenset()
    if new_tags <= tags:
        return txn
    return txn._replace(tags=tags | new_tags)


def _parse_config(config: str | None) -> dict[str, list[str]]:
    if not config:
        raise ValueError(
            "tag_travel requires a config, e.g. {'travel_accounts': ['Expenses:Travel']}"
        )
    settings = literal_eval(config)
    if not isinstance(settings, dict) or not set(settings) <= _CONFIG_KEYS:
        raise ValueError(
            f"tag_travel config must be a dict with keys {sorted(_CONFIG_KEYS)}; got {config!r}"
        )
    return settings


def _matcher(accounts: Sequence[str]) -> Callable[[str], bool]:
    """Whether an account is one of ``accounts`` or a subaccount of one."""
    matchers = [account_lib.parent_matcher(account) for account in accounts]
    return lambda account: any(match(account) for match in matchers)
