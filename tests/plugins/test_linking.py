import datetime

from beancount.core.flags import FLAG_OKAY

from beancount_sg.builders import A, B, P, T
from beancount_sg.plugins.linking import Linker

LINKER = Linker("Assets:Transfers")


def transfer(date, number, *, other="Assets:Checking", links=(), currency="USD"):
    """A transaction moving `number` into Assets:Transfers from `other`."""
    units = A(number, currency)
    return T(
        date,
        narration="Transfer",
        links=links,
        postings=[P("Assets:Transfers", units), P(other, -units)],
    )


def test_matching_pair_is_linked_and_flagged():
    out, inn = LINKER([transfer("2020-01-15", -100), transfer("2020-01-15", 100)])
    for txn in (out, inn):
        assert txn.links == {"x-Transfers-20200115-100"}
        assert [p.flag for p in txn.postings] == [FLAG_OKAY, None]


def test_key_uses_normalized_absolute_amount():
    out, inn = LINKER([transfer("2020-01-15", "-12.5"), transfer("2020-01-15", "12.50")])
    assert out.links == inn.links == {"x-Transfers-20200115-12.5"}


def test_key_uses_last_account_component():
    out, inn = LINKER(
        [
            T("2020-01-15", postings=[P("Assets:Transfers:Savings", A(-5, "USD"))]),
            T("2020-01-15", postings=[P("Assets:Transfers:Savings", A(5, "USD"))]),
        ]
    )
    assert out.links == inn.links == {"x-Savings-20200115-5"}


def test_different_days_are_not_linked():
    entries = [transfer("2020-01-15", -100), transfer("2020-01-16", 100)]
    assert LINKER(entries) == entries


def test_date_offset_shifts_the_key_date():
    linker = Linker("Assets:Transfers", date_format="%Y%m", date_offset=datetime.timedelta(days=5))
    out, inn = linker([transfer("2020-01-28", -100), transfer("2020-02-02", 100)])
    assert out.links == inn.links == {"x-Transfers-202002-100"}


def test_unbalanced_group_is_not_linked():
    linker = Linker("Assets:Transfers", include_amount=False)
    entries = [transfer("2020-01-15", -100), transfer("2020-01-15", 90)]
    assert linker(entries) == entries


def test_single_transaction_is_not_linked():
    entries = [transfer("2020-01-15", -100)]
    assert LINKER(entries) == entries


def test_mixed_currencies_are_not_linked():
    entries = [transfer("2020-01-15", -100), transfer("2020-01-15", 100, currency="EUR")]
    assert LINKER(entries) == entries


def test_group_of_three_that_cancels_is_linked():
    linker = Linker("Assets:Transfers", date_format="%Y%m", include_amount=False)
    txns = linker(
        [
            transfer("2020-01-02", -100),
            transfer("2020-01-10", 60),
            transfer("2020-01-20", 40),
        ]
    )
    assert all(txn.links == {"x-Transfers-202001"} for txn in txns)


def test_existing_link_is_used_as_key():
    out, inn = LINKER(
        [
            transfer("2020-01-15", -100, links=["x-manual"]),
            transfer("2020-02-20", 100, links=["x-manual", "other"]),
        ]
    )
    assert out.links == {"x-manual"}
    assert inn.links == {"x-manual", "other"}
    assert out.postings[0].flag == inn.postings[0].flag == FLAG_OKAY


def test_links_with_other_prefixes_are_ignored():
    out, inn = LINKER(
        [
            transfer("2020-01-15", -100, links=["y-other"]),
            transfer("2020-01-15", 100),
        ]
    )
    assert out.links == {"y-other", "x-Transfers-20200115-100"}
    assert inn.links == {"x-Transfers-20200115-100"}


def test_sibling_account_with_same_prefix_is_not_linkable():
    assert LINKER.is_linkable(P("Assets:Transfers"))
    assert LINKER.is_linkable(P("Assets:Transfers:Savings"))
    assert not LINKER.is_linkable(P("Assets:TransfersOld"))


def test_only_first_linkable_posting_is_used():
    txn = T(
        "2020-01-15",
        postings=[
            P("Assets:Transfers", A(-100, "USD")),
            P("Assets:Transfers", A(30, "USD")),
            P("Assets:Checking", A(70, "USD")),
        ],
    )
    out, inn = LINKER([txn, transfer("2020-01-15", 100)])
    assert [p.flag for p in out.postings] == [FLAG_OKAY, None, None]
    assert out.links == inn.links


def test_other_entries_are_untouched_and_input_is_not_mutated():
    balance = B("2020-01-01", "Assets:Checking", A(0, "USD"))
    unrelated = T("2020-01-15", postings=[P("Assets:Checking", A(-5, "USD"))])
    entries = [balance, unrelated, transfer("2020-01-15", -100), transfer("2020-01-15", 100)]
    snapshot = list(entries)
    new_entries = LINKER(entries)
    assert entries == snapshot
    assert new_entries[0] is balance
    assert new_entries[1] is unrelated
    assert all(not txn.links for txn in entries[2:])


def test_already_linked_transactions_keep_identity():
    entries = LINKER([transfer("2020-01-15", -100), transfer("2020-01-15", 100)])
    assert all(new is old for new, old in zip(LINKER(entries), entries, strict=True))
