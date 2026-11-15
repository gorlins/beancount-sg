import datetime

import pytest

from beancount_sg.plugins.tag_travel import trip_tag
from beancount_sg.testing import load_txns

CONFIG = "{'travel_accounts': ['Expenses:Travel'], 'conditional_accounts': ['Expenses:Food']}"
PLUGIN = ("beancount_sg.plugins.tag_travel", CONFIG)


def tags(ledger: str, plugin=PLUGIN) -> list[set[str]]:
    return [set(txn.tags) for txn in load_txns(ledger, [plugin])]


def spend(date: str, account: str, narration: str = "Spend") -> str:
    return f"""
{date} * "{narration}"
  {account}  10.00 USD
  Assets:Cash
"""


def test_travel_accounts_always_tagged_and_conditional_only_while_away():
    assert tags(
        spend("2024-02-01", "Expenses:Travel:Flights")  # booked from home
        + spend("2024-02-02", "Expenses:Food")  # at home
        + '2024-03-04 event "travel" "New York City"\n'
        + spend("2024-03-05", "Expenses:Travel:Hotel")
        + spend("2024-03-05", "Expenses:Food")
        + spend("2024-03-05", "Expenses:Books")  # neither kind of account
        + '2024-03-09 event "travel" "home"\n'
        + spend("2024-03-10", "Expenses:Food")
        + spend("2024-03-10", "Expenses:Travel:Taxi")
    ) == [
        {"travel"},
        set(),
        {"travel", "new-york-city-2024"},
        {"travel", "new-york-city-2024"},
        set(),
        set(),
        {"travel"},
    ]


def test_event_applies_to_transactions_on_its_date_whatever_the_line_order():
    assert tags(
        spend("2024-03-04", "Expenses:Food", "Lunch on arrival")
        + '2024-03-04 event "travel" "Boston"\n'
        + '2024-03-08 event "travel" "home"\n'
        + spend("2024-03-08", "Expenses:Food", "Dinner at home")
    ) == [{"travel", "boston-2024"}, set()]


def test_moving_between_trips_changes_the_trip_tag():
    assert tags(
        '2024-03-04 event "travel" "Boston"\n'
        + spend("2024-03-05", "Expenses:Food")
        + '2024-03-07 event "travel" "Montréal, QC"\n'
        + spend("2024-03-08", "Expenses:Food")
    ) == [{"travel", "boston-2024"}, {"travel", "montreal-qc-2024"}]


def test_other_event_types_are_ignored():
    assert tags(
        '2024-03-04 event "location" "Boston"\n' + spend("2024-03-05", "Expenses:Food")
    ) == [set()]


def test_sibling_account_with_same_prefix_is_not_matched():
    assert tags(
        '2024-03-04 event "travel" "Boston"\n' + spend("2024-03-05", "Expenses:FoodDelivery")
    ) == [set()]


def test_existing_tags_are_kept():
    ledger = '2024-03-04 event "travel" "Boston"\n' + spend("2024-03-05", "Expenses:Food")
    ledger = ledger.replace('"Spend"', '"Spend" #work')
    assert tags(ledger) == [{"work", "travel", "boston-2024"}]


def test_separate_loads_do_not_share_the_location():
    tags('2024-03-04 event "travel" "Boston"\n')
    assert tags(spend("2024-03-05", "Expenses:Food")) == [set()]


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("New York City", "new-york-city-2024"),
        ("Zürich", "zurich-2024"),
        ("  St. John's, NL  ", "st-john-s-nl-2024"),
    ],
)
def test_trip_tag(location, expected):
    assert trip_tag(location, datetime.date(2024, 5, 1)) == expected


def test_multiline_config_is_accepted():
    config = """{
  'travel_accounts': ['Expenses:Travel'],
  'conditional_accounts': ['Expenses:Food'],
}"""
    assert tags(
        '2024-03-04 event "travel" "Boston"\n' + spend("2024-03-05", "Expenses:Food"),
        ("beancount_sg.plugins.tag_travel", config),
    ) == [{"travel", "boston-2024"}]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (None, "requires a config"),
        ("{'travel_acounts': ['Expenses:Travel']}", "must be a dict with keys"),
    ],
)
def test_bad_config_is_a_load_error(config, message):
    plugin = "beancount_sg.plugins.tag_travel" if config is None else (PLUGIN[0], config)
    with pytest.raises(AssertionError, match=message):
        tags(spend("2024-03-05", "Expenses:Food"), plugin)
