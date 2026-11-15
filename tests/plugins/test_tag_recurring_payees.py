from beancount.core.data import filter_txns

from beancount_sg.plugins.tag_recurring_payees import tag_recurring_payees
from beancount_sg.testing import load, load_txns

PLUGIN = "beancount_sg.plugins.tag_recurring_payees"

LEDGER = """
    2024-01-05 * "Netflix" "Subscription"
      Liabilities:CreditCard  -15.49 USD
      Expenses:Entertainment

    2024-02-05 * "Netflix" "Subscription" #recurring
      Liabilities:CreditCard  -15.49 USD
      Expenses:Entertainment

    2024-03-05 * "Netflix" "Subscription"
      Liabilities:CreditCard  -15.49 USD
      Expenses:Entertainment

    2024-03-06 * "NETFLIX" "Different spelling"
      Liabilities:CreditCard  -15.49 USD
      Expenses:Entertainment

    2024-03-07 * "Grocer" "Food" #weekly
      Liabilities:CreditCard  -50.00 USD
      Expenses:Food

    2024-03-08 * "No payee, just a narration"
      Liabilities:CreditCard  -5.00 USD
      Expenses:Food
    """


def payee_tags(plugin=PLUGIN) -> list[tuple[str | None, set[str]]]:
    return [(txn.payee, set(txn.tags)) for txn in load_txns(LEDGER, [plugin])]


def test_every_transaction_from_a_tagged_payee_is_tagged():
    assert payee_tags() == [
        ("Netflix", {"recurring"}),  # earlier than the tagged one
        ("Netflix", {"recurring"}),
        ("Netflix", {"recurring"}),
        ("NETFLIX", set()),  # payees must match exactly
        ("Grocer", {"weekly"}),
        (None, set()),
    ]


def test_tag_can_be_configured():
    assert payee_tags((PLUGIN, "weekly")) == [
        ("Netflix", set()),
        ("Netflix", {"recurring"}),
        ("Netflix", set()),
        ("NETFLIX", set()),
        ("Grocer", {"weekly"}),
        (None, set()),
    ]


def test_configured_tag_is_added_even_if_default_tag_is_present():
    txns = load_txns(
        """
        2024-01-05 * "Gym" "Membership" #monthly
          Liabilities:CreditCard  -40.00 USD
          Expenses:Health

        2024-02-05 * "Gym" "Membership" #recurring
          Liabilities:CreditCard  -40.00 USD
          Expenses:Health
        """,
        [(PLUGIN, "monthly")],
    )
    assert [set(txn.tags) for txn in txns] == [{"monthly"}, {"monthly", "recurring"}]


def test_input_is_not_mutated():
    entries, options_map = load(LEDGER)
    new_entries, errors = tag_recurring_payees(entries, options_map)
    assert errors == []
    assert next(filter_txns(entries)).tags == frozenset()
    assert next(filter_txns(new_entries)).tags == {"recurring"}
