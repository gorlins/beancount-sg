import datetime
import html
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from beancount import loader
from beancount.core.data import filter_txns
from fava.application import create_app
from fava.core.filter_parser import parse_filter

from beancount_sg.builders import A, P, T
from beancount_sg.ext.travel import (
    ledger_trips,
    travel_spending,
    trip_filter,
    trip_tags,
)

ENABLE = 'custom "fava-extension" "beancount_sg.ext.travel"'

LEDGER = f"""
option "title" "Test"
2020-01-01 {ENABLE}

2020-01-01 open Assets:Checking
2020-01-01 open Expenses:Travel:Flights
2020-01-01 open Expenses:Travel:Hotels
2020-01-01 open Expenses:Food
2020-01-01 open Income:Refunds

2025-01-10 * "Airline" "Flight to Miami" #travel #miami-2025
  Expenses:Travel:Flights  300.00 USD
  Assets:Checking

2025-02-01 * "Hotel" "Miami hotel" #travel #miami-2025 #reimbursable
  Expenses:Travel:Hotels  400.00 USD
  Assets:Checking

2025-02-02 * "Cafe" "Lunch in Miami" #travel #miami-2025
  Expenses:Food  25.00 USD
  Assets:Checking

2025-02-05 * "Airline" "Partial refund" #travel #miami-2025
  Expenses:Travel:Flights  -50.00 USD
  Assets:Checking

2025-06-01 * "Airline" "Flight to Paris" #travel #paris-2025 #recurring
  Expenses:Travel:Flights  800.00 USD
  Assets:Checking

2025-07-01 * "Taxi" "Untagged trip" #travel
  Expenses:Travel:Flights  60.00 USD
  Assets:Checking

2025-07-02 * "Cafe" "Untagged lunch" #travel
  Expenses:Food  15.00 USD
  Assets:Checking

2025-07-03 * "Grocer" "Not travel" #recurring
  Expenses:Food  100.00 USD
  Assets:Checking

2024-03-01 * "Airline" "Old trip" #travel #nyc-2024
  Expenses:Travel:Flights  200.00 USD
  Assets:Checking
"""


def load():
    entries, errors, _ = loader.load_string(LEDGER)
    assert not errors
    return entries


def spend(entries=None):
    entries = entries or load()
    return travel_spending(entries, "Expenses", ledger_trips(entries))


def test_trips_are_tags_only_used_on_travel():
    # #recurring is also on a transaction without #travel, so it isn't a trip.
    assert ledger_trips(load()) == {"miami-2025", "nyc-2024", "paris-2025", "reimbursable"}
    txn = T("2025-01-01", tags={"travel", "recurring", "miami-2025"}, postings=[])
    assert trip_tags(txn, ledger_trips(load())) == ["miami-2025"]


def test_a_trip_tag_used_without_travel_is_not_a_trip():
    entries, _, _ = loader.load_string(
        LEDGER
        + """
2025-08-01 * "Cafe" "Forgot the travel tag" #paris-2025
  Expenses:Food  5.00 USD
  Assets:Checking
"""
    )
    assert "paris-2025" not in ledger_trips(entries)
    no_trip = next(trip for trip in spend(entries).trips if not trip.tag)
    assert no_trip.total == [A("875.00", "USD")]  # with the Paris flight


def test_spending_by_trip_and_account():
    spending = spend()
    rows, trips = spending.rows, spending.trips
    assert [(row.trip, row.account, row.amount) for row in rows] == [
        (None, "Expenses:Food", A("15.00", "USD")),
        (None, "Expenses:Travel:Flights", A("60.00", "USD")),
        ("miami-2025", "Expenses:Food", A("25.00", "USD")),
        ("miami-2025", "Expenses:Travel:Flights", A("250.00", "USD")),  # with the refund
        ("miami-2025", "Expenses:Travel:Hotels", A("400.00", "USD")),
        ("nyc-2024", "Expenses:Travel:Flights", A("200.00", "USD")),
        ("paris-2025", "Expenses:Travel:Flights", A("800.00", "USD")),
    ]
    assert [(trip.tag, trip.first, trip.last, trip.transactions, trip.total) for trip in trips] == [
        ("nyc-2024", datetime.date(2024, 3, 1), datetime.date(2024, 3, 1), 1, [A("200.00", "USD")]),
        (
            "miami-2025",
            datetime.date(2025, 1, 10),
            datetime.date(2025, 2, 5),
            4,
            [A("675.00", "USD")],
        ),
        (
            "paris-2025",
            datetime.date(2025, 6, 1),
            datetime.date(2025, 6, 1),
            1,
            [A("800.00", "USD")],
        ),
        (None, datetime.date(2025, 7, 1), datetime.date(2025, 7, 2), 2, [A("75.00", "USD")]),
    ]


def test_only_expense_postings_count():
    txn = T(
        "2025-01-01",
        tags={"travel", "rome-2025"},
        postings=[
            P("Expenses:Travel:Flights", A("100.00", "USD")),
            P("Income:Refunds", A("-30.00", "USD")),
            P("Assets:Checking", A("-70.00", "USD")),
        ],
    )
    rows = travel_spending([txn], "Expenses", {"rome-2025"}).rows
    assert [(row.account, row.amount) for row in rows] == [
        ("Expenses:Travel:Flights", A("100.00", "USD"))
    ]


def matching(fava_filter):
    """The narrations of the ledger's transactions that a Fava filter matches."""
    expression = parse_filter(fava_filter)
    return sorted(txn.narration for txn in filter_txns(load()) if expression(txn))


def test_trip_filters_select_the_trip_or_untagged_travel():
    tags = ["miami-2025", "nyc-2024", "paris-2025"]
    assert matching(trip_filter("paris-2025", tags)) == ["Flight to Paris"]
    assert matching(trip_filter(None, tags)) == ["Untagged lunch", "Untagged trip"]


def page(tmp_path, text=LEDGER, query=""):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(text)
    response = create_app([ledger], load=True).test_client().get(f"/test/extension/Travel/{query}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(body):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


def charts(body):
    [data] = re.findall(
        r'<svelte-component type="charts"><script type="application/json">(.*?)</script>',
        body,
        re.DOTALL,
    )
    return {chart["label"]: chart["data"] for chart in json.loads(data)}


def leaves(node):
    if not node["children"]:
        return {node["account"]: node["balance"]}
    return {k: v for child in node["children"] for k, v in leaves(child).items()}


def chart_links(body):
    [data] = re.findall(
        r'<script type="application/json" id="travel-chart-links">(.*?)</script>', body
    )
    return json.loads(data)


def link_target(url):
    """A link's path and its filter."""
    parts = urlsplit(html.unescape(url))
    return unquote(parts.path), parse_qs(parts.query).get("filter", [""])[0]


def test_summary_calls_out_untagged_spending(tmp_path):
    body = text(page(tmp_path))
    assert "Travel spending: 1750.00 USD on 3 trips." in body
    assert "75.00 USD of it (2 transactions) isn't tagged with a trip." in body


def test_table_lists_trips_then_untagged(tmp_path):
    body = text(page(tmp_path))
    assert "#nyc-2024 2024-03-01 2024-03-01 1 200.00 USD" in body
    assert "#miami-2025 2025-01-10 2025-02-05 4 675.00 USD" in body
    assert "no trip 2025-07-01 2025-07-02 2 75.00 USD" in body
    assert "Total 8 1750.00 USD" in body
    assert body.index("#paris-2025") < body.index("no trip 2025")


def test_charts_by_trip_and_by_category(tmp_path):
    found = charts(page(tmp_path))
    assert set(found) == {"By trip", "By category"}
    by_trip = found["By trip"]
    assert by_trip["account"] == "All trips"
    assert by_trip["balance_children"] == {"USD": "1750.00"}
    assert leaves(by_trip)["All trips:miami-2025:Travel:Hotels"] == {"USD": "400.00"}
    assert leaves(by_trip)["All trips:no trip:Food"] == {"USD": "15.00"}
    by_category = found["By category"]
    assert by_category["account"] == "Expenses"
    assert leaves(by_category)["Expenses:Travel:Flights:miami-2025"] == {"USD": "250.00"}
    assert leaves(by_category)["Expenses:Food:no trip"] == {"USD": "15.00"}


@pytest.mark.parametrize(
    ("node", "path", "narrations"),
    [
        ("All trips", "/test/income_statement/", None),  # all travel
        ("All trips:paris-2025", "/test/income_statement/", ["Flight to Paris"]),
        ("All trips:no trip", "/test/income_statement/", ["Untagged lunch", "Untagged trip"]),
        (
            "All trips:miami-2025:Travel",
            "/test/account/Expenses:Travel/",
            ["Flight to Miami", "Lunch in Miami", "Miami hotel", "Partial refund"],
        ),
        ("Expenses:Travel:Flights", "/test/account/Expenses:Travel:Flights/", None),
        (
            "Expenses:Food:no trip",
            "/test/account/Expenses:Food/",
            ["Untagged lunch", "Untagged trip"],
        ),
    ],
)
def test_chart_nodes_link_to_tag_filtered_pages(tmp_path, node, path, narrations):
    links = chart_links(page(tmp_path))
    link_path, fava_filter = link_target(links[node])
    assert link_path == path
    if narrations is None:  # all travel transactions
        assert fava_filter == "#travel"
    else:
        assert matching(fava_filter) == narrations


def names(node):
    """The names of a chart node and all its descendants."""
    return [node["account"], *(name for child in node["children"] for name in names(child))]


def test_every_chart_node_has_a_link(tmp_path):
    body = page(tmp_path)
    links = chart_links(body)
    for chart in charts(body).values():
        assert set(names(chart)) <= set(links)


def test_table_links_keep_the_current_filter(tmp_path):
    body = page(tmp_path, query="?filter=Miami")
    [href] = re.findall(r'<a href="([^"]+)">#miami-2025</a>', body)
    _, fava_filter = link_target(href)
    assert matching(fava_filter) == ["Flight to Miami", "Lunch in Miami", "Miami hotel"]


def test_respects_the_time_filter(tmp_path):
    body = text(page(tmp_path, query="?time=2024"))
    assert "Travel spending: 200.00 USD on 1 trip." in body
    assert "All of it is tagged with a trip." in body
    assert "several trip tags" not in body


def test_any_other_tag_is_a_trip(tmp_path):
    ledger = LEDGER.replace("#paris-2025", "#work-offsite")
    body = text(page(tmp_path, ledger))
    assert "#work-offsite 2025-06-01 2025-06-01 1 800.00 USD" in body


def test_several_trip_tags_count_towards_the_first_and_are_listed(tmp_path):
    spending = spend()
    # Not the Paris flight: #recurring is also used without #travel.
    assert [txn.narration for txn in spending.several_trips] == ["Miami hotel"]
    body = page(tmp_path)
    warning = text(body[body.index('<ul class="error">') : body.index("</ul>")])
    assert "Hotel Miami hotel: #miami-2025, #reimbursable" in warning
    assert "Paris" not in warning
    # Counted towards #miami-2025; #reimbursable isn't a trip.
    assert "#reimbursable" not in text(body[body.index("<table") :])


def test_trips_come_from_the_whole_ledger_whatever_the_filter(tmp_path):
    # June 2025 has the Paris flight (#recurring) but not the grocer's, which makes
    # #recurring a non-trip.
    body = page(tmp_path, query="?time=2025-06")
    report = text(body[body.index("<h2>Travel</h2>") : body.index("<details>")])
    assert "#paris-2025 2025-06-01 2025-06-01 1 800.00 USD" in report
    assert "#recurring" not in report
    assert "several trip tags" not in report


def test_without_travel(tmp_path):
    body = page(tmp_path, LEDGER.replace("#travel", ""))
    assert "No travel spending in the current filter" in body
    assert "svelte-component" not in body
