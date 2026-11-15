"""Tag travel spending, and everyday spending while away, with the trip.

Record where you are with ``travel`` events, and ``home`` when you get back:

    2024-03-04 event "travel" "New York City"
    2024-03-09 event "travel" "home"

Configure which accounts to tag, as a Python dict:

    plugin "beancount_sg.plugins.tag_travel" "{
      'travel_accounts': ['Expenses:Travel'],
      'conditional_accounts': ['Expenses:Food', 'Expenses:Transport'],
      'include_return_day': True,
    }"

Then a transaction with a posting to (a subaccount of) one of these accounts
is tagged:

- ``travel_accounts``: always ``#travel``, plus the trip tag while away, so
  e.g. flights booked from home are still travel;
- ``conditional_accounts``: ``#travel`` and the trip tag, only while away.

The trip tag is the location and the year the trip started, slugified, e.g.
``#new-york-city-2024`` or ``#zurich-2024``.

A trip starts on its event's date, including transactions on that date, and
lasts until the next ``travel`` event. Before the first event you're at home.

With ``include_return_day`` (the default), the day you get home still counts as
part of the trip, e.g. the taxi from the airport, so a ``home`` event takes
effect the day after its date; above, the trip covers March 4 to 9. Set it to
``False`` to end the trip on the ``home`` event's date instead. Either way, a
new trip starting on the day you get home takes over from that day.

Usage::

    plugin "beancount_sg.plugins.tag_travel" "{'travel_accounts': [...], ...}"
"""

from __future__ import annotations

import bisect
import datetime
import functools
from ast import literal_eval
from collections.abc import Callable, Sequence
from typing import Any

from beancount.core import account as account_lib
from beancount.core.data import Directive, Event, Transaction
from slugify import slugify

from .plugin_helpers import map_transactions

__plugins__ = ("tag_travel",)

TAG = "travel"
EVENT_TYPE = "travel"
HOME = "home"

_CONFIG_KEYS = {"travel_accounts", "conditional_accounts", "include_return_day"}


def tag_travel(
    entries: list[Directive], options_map: dict[str, Any], config: str | None = None
) -> tuple[list[Directive], list[Any]]:
    """Tag transactions in the configured accounts with #travel and the current trip."""
    settings = _parse_config(config)
    travel = _matcher(settings.get("travel_accounts", []))
    conditional = _matcher(settings.get("conditional_accounts", []))
    dates, trips = trip_timeline(
        entries, include_return_day=settings.get("include_return_day", True)
    )
    return map_transactions(
        entries,
        functools.partial(
            tag_transaction, dates=dates, trips=trips, travel=travel, conditional=conditional
        ),
    )


def trip_timeline(
    entries: list[Directive], *, include_return_day: bool = True
) -> tuple[list[datetime.date], list[str | None]]:
    """Parallel lists of the dates trips take effect and their tags (None at home).

    Entries are in date order, and same-date events in file order, so the last
    event on a date wins. With ``include_return_day``, ``home`` takes effect the
    day after its event, unless another trip starts on the event's own date.
    """
    events = [e for e in entries if isinstance(e, Event) and e.type == EVENT_TYPE]
    dates: list[datetime.date] = []
    trips: list[str | None] = []
    for i, event in enumerate(events):
        if event.description.strip().lower() != HOME:
            dates.append(event.date)
            trips.append(trip_tag(event.description, event.date))
            continue
        date = event.date
        if include_return_day:
            # Leaving again the same day: the new trip takes over, so skip this one.
            if i + 1 < len(events) and events[i + 1].date == date:
                continue
            # This stays in date order: the next event is at least a day later, and if
            # it's exactly a day later it comes after this one, so it wins that date.
            date += datetime.timedelta(days=1)
        dates.append(date)
        trips.append(None)
    return dates, trips


def trip_tag(location: str, date: datetime.date) -> str:
    """A tag for a trip, e.g. ``new-york-city-2024`` for "New York City" in 2024."""
    return f"{slugify(location)}-{date.year}"


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


def _parse_config(config: str | None) -> dict[str, Any]:
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
