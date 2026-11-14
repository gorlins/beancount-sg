import pytest

from beancount_sg.plugins.check_numbers import META_KEY, check_numbers
from beancount_sg.testing import load, load_txns

PLUGIN = "beancount_sg.plugins.check_numbers"


def check_no(narration: str, amount: str = "-250.00", meta: str = "") -> str | None:
    """The check number recorded for a single transaction, if any."""
    txn = load_txns(
        f"""
2024-03-04 * "{narration}"{meta}
  Assets:Checking  {amount} USD
  Expenses:Home
""",
        [PLUGIN],
    )[0]
    return txn.meta.get(META_KEY)


@pytest.mark.parametrize(
    ("narration", "expected"),
    [
        ("CHECK #1042", "1042"),
        ("Check #1042 to plumber", "1042"),
        ("check paid #1042", "1042"),
        ("NOTE #77", "77"),
        ("CHECK #001042", "1042"),  # leading zeros dropped
    ],
)
def test_check_payment_gets_check_number(narration, expected):
    assert check_no(narration) == expected


@pytest.mark.parametrize(
    "narration",
    [
        "CHECK DEPOSIT",  # no number
        "Transfer to Checking #1042",  # "Checking" isn't the word "check"
        "Debit card #1042",  # not a check
    ],
)
def test_other_narrations_are_ignored(narration):
    assert check_no(narration) is None


def test_deposits_are_ignored():
    assert check_no("CHECK #1042", amount="250.00") is None


def test_existing_check_number_is_kept():
    assert check_no("CHECK #1042", meta='\n  check_no: "999"') == "999"


def test_input_is_not_mutated():
    entries, options_map = load("""
        2024-03-04 * "CHECK #1042"
          Assets:Checking  -250.00 USD
          Expenses:Home
        """)
    new_entries, errors = check_numbers(entries, options_map)
    assert errors == []
    assert META_KEY not in entries[-1].meta
    assert new_entries[-1].meta[META_KEY] == "1042"
