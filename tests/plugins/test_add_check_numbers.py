import pytest

from beancount_sg.plugins.add_check_numbers import LEGACY_KEYS, META_KEY, add_check_numbers
from beancount_sg.testing import load, load_txns

PLUGIN = "beancount_sg.plugins.add_check_numbers"


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
        "NOTE #77",  # only checks count
        "#1042 check",  # the number must follow the word
    ],
)
def test_other_narrations_are_ignored(narration):
    assert check_no(narration) is None


def test_deposits_are_ignored():
    assert check_no("CHECK #1042", amount="250.00") is None


def payment_check_no(postings: str) -> str | None:
    txn = load_txns(f'2024-03-04 * "CHECK #1042"\n{postings}', [PLUGIN])[0]
    return txn.meta.get(META_KEY)


def test_posting_order_does_not_matter():
    assert payment_check_no("  Expenses:Home  250.00 USD\n  Assets:Checking  -250.00 USD\n") == (
        "1042"
    )


def test_check_written_from_a_liability_account():
    assert payment_check_no("  Liabilities:HELOC  -250.00 USD\n  Expenses:Home\n") == "1042"


def test_more_than_one_paying_account_is_ignored():
    assert (
        payment_check_no(
            "  Assets:Checking  -200.00 USD\n  Assets:Savings  -50.00 USD\n  Expenses:Home\n"
        )
        is None
    )


def test_payment_from_an_income_account_is_ignored():
    assert payment_check_no("  Income:Refunds  -250.00 USD\n  Expenses:Home\n") is None


def test_existing_check_number_is_kept():
    assert check_no("CHECK #1042", meta='\n  check-no: "999"') == "999"


def test_input_is_not_mutated():
    entries, options_map = load("""
        2024-03-04 * "CHECK #1042"
          Assets:Checking  -250.00 USD
          Expenses:Home
        """)
    new_entries, errors = add_check_numbers(entries, options_map)
    assert errors == []
    assert META_KEY not in entries[-1].meta
    assert new_entries[-1].meta[META_KEY] == "1042"


def converted(narration: str, meta: str, *, plugin: bool = True) -> tuple[dict, list]:
    """A transaction's check-number metadata after the plugin (or as written), and errors."""
    entries, options_map = load(f"""
2024-03-04 * "{narration}"{meta}
  Assets:Checking  -250.00 USD
  Expenses:Home
""")
    errors = []
    if plugin:
        entries, errors = add_check_numbers(entries, options_map)
    keys = (META_KEY, *LEGACY_KEYS)
    return {key: entries[-1].meta[key] for key in keys if key in entries[-1].meta}, errors


@pytest.mark.parametrize("legacy", LEGACY_KEYS)
@pytest.mark.parametrize("value", ['"1042"', '"01042"', "1042"])
def test_legacy_key_matching_the_narration_is_converted(legacy, value):
    assert converted("CHECK #1042", f"\n  {legacy}: {value}") == ({META_KEY: "1042"}, [])


def test_legacy_key_without_a_number_in_the_narration_is_converted():
    # E.g. a deposit, which isn't a payment by check.
    assert converted("Deposit", '\n  checknum: "0517"') == ({META_KEY: "517"}, [])


def test_legacy_keys_matching_check_no_are_removed_and_it_is_kept():
    meta = '\n  check-no: "01042"\n  check_no: 1042\n  checknum: "1042"'
    assert converted("CHECK #999", meta) == ({META_KEY: "01042"}, [])


@pytest.mark.parametrize(
    ("narration", "meta", "found"),
    [
        ("CHECK #1042", '\n  check_no: "1043"', "check_no '1043', narration '1042'"),
        ("Deposit", '\n  check_no: "7"\n  checknum: "8"', "check_no '7', checknum '8'"),
        ("CHECK #1", '\n  check-no: "2"\n  checknum: "2.5"', "checknum '2.5', check-no '2'"),
        ("Deposit", '\n  check_no: "n/a"', "check_no 'n/a'"),
        # A number, not truncated to 2.
        ("CHECK #2", "\n  checknum: 2.5", "checknum '2.5', narration '2'"),
        ("CHECK #1042", "\n  check_no: 1043", "check_no '1043', narration '1042'"),
    ],
)
def test_mismatched_check_numbers_are_an_error_and_left_alone(narration, meta, found):
    before, _ = converted(narration, meta, plugin=False)
    after, errors = converted(narration, meta)
    assert after == before
    [error] = errors
    assert error.message == f"Mismatched check numbers: {found}"
    assert error.entry.narration == narration
