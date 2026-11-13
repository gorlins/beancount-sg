import copy
import datetime
from decimal import Decimal

from beancount.core.display_context import DisplayContext
from beancount.core.flags import FLAG_OKAY, FLAG_TRANSFER, FLAG_WARNING
from beancount.parser.options import OPTIONS_DEFAULTS

from beancount_sg.builders import A, B, P, T
from beancount_sg.plugins._linking import Linker

LINKER = Linker("Assets:Transfers")


def options(**precisions):
    """An options map whose display context knows each currency's usual precision."""
    dcontext = DisplayContext()
    for currency, example in precisions.items():
        dcontext.update(Decimal(example), currency)
    return {**copy.deepcopy(OPTIONS_DEFAULTS), "dcontext": dcontext}


def link(entries, linker=LINKER, options_map=None):
    new_entries, errors = linker(entries, options_map or options())
    assert errors == []
    return new_entries


def transfer(date, number, *, links=(), currency="USD", flag=None):
    """A transaction moving `number` into Assets:Transfers from Assets:Checking."""
    units = A(number, currency)
    return T(
        date,
        narration="Transfer",
        links=links,
        postings=[P("Assets:Transfers", units, flag=flag), P("Assets:Checking", -units)],
    )


def test_matching_pair_is_linked_and_flagged_okay():
    out, inn = link([transfer("2020-01-15", -100), transfer("2020-01-15", 100)])
    for txn in (out, inn):
        assert txn.links == {"x-Transfers-20200115-100"}
        assert [p.flag for p in txn.postings] == [FLAG_OKAY, None]


def test_unmatched_posting_is_flagged_warning():
    [txn] = link([transfer("2020-01-15", -100)])
    assert not txn.links
    assert [p.flag for p in txn.postings] == [FLAG_WARNING, None]


def test_previously_okay_posting_is_flagged_warning_if_unmatched():
    [txn] = link([transfer("2020-01-15", -100, flag=FLAG_OKAY)])
    assert [p.flag for p in txn.postings] == [FLAG_WARNING, None]


def test_amount_uses_currency_precision():
    out, inn = link(
        [transfer("2020-01-15", "-1.1"), transfer("2020-01-15", "1.10")],
        options_map=options(USD="0.00"),
    )
    assert out.links == inn.links == {"x-Transfers-20200115-1.10"}


def test_amount_without_known_precision_is_used_as_is():
    out, inn = link([transfer("2020-01-15", "-1.10"), transfer("2020-01-15", "1.10")])
    assert out.links == inn.links == {"x-Transfers-20200115-1.10"}


def test_window_without_date_format_omits_the_date():
    linker = Linker("Assets:Transfers", windows=[(None, None)])
    out, inn = link([transfer("2020-01-15", -100), transfer("2021-06-30", 100)], linker)
    assert out.links == inn.links == {"x-Transfers-100"}


def test_transaction_flag_is_not_changed():
    txns = link(
        [
            T("2020-01-15", flag=FLAG_WARNING, postings=[P("Assets:Transfers", A(-5, "USD"))]),
            T("2020-01-15", flag=FLAG_OKAY, postings=[P("Assets:Transfers", A(5, "USD"))]),
            T("2020-01-16", flag=FLAG_OKAY, postings=[P("Assets:Transfers", A(7, "USD"))]),
        ]
    )
    assert [txn.flag for txn in txns] == [FLAG_WARNING, FLAG_OKAY, FLAG_OKAY]
    assert [txn.postings[0].flag for txn in txns] == [FLAG_OKAY, FLAG_OKAY, FLAG_WARNING]


def test_special_posting_flag_is_overwritten():
    out, inn = link([transfer("2020-01-15", -100, flag=FLAG_TRANSFER), transfer("2020-01-16", 100)])
    assert out.postings[0].flag == inn.postings[0].flag == FLAG_WARNING


def test_key_uses_account_leaf():
    out, inn = link(
        [
            T("2020-01-15", postings=[P("Assets:Transfers:Savings", A(-5, "USD"))]),
            T("2020-01-15", postings=[P("Assets:Transfers:Savings", A(5, "USD"))]),
        ]
    )
    assert out.links == inn.links == {"x-Savings-20200115-5"}


def test_subaccounts_with_the_same_leaf_share_a_key():
    # A known weakness of using only the leaf; see test_account_key_can_be_overridden.
    home, office = link(
        [
            T("2020-01-15", postings=[P("Assets:Transfers:Home:Savings", A(-5, "USD"))]),
            T("2020-01-15", postings=[P("Assets:Transfers:Office:Savings", A(5, "USD"))]),
        ]
    )
    assert home.links == office.links == {"x-Savings-20200115-5"}


def test_account_key_can_be_overridden():
    class PathLinker(Linker):
        def account_key(self, account):
            return account.removeprefix(self.account + ":").replace(":", ".")

    home_out, home_in, office = link(
        [
            T("2020-01-15", postings=[P("Assets:Transfers:Home:Savings", A(-5, "USD"))]),
            T("2020-01-15", postings=[P("Assets:Transfers:Home:Savings", A(5, "USD"))]),
            T("2020-01-15", postings=[P("Assets:Transfers:Office:Savings", A(5, "USD"))]),
        ],
        PathLinker("Assets:Transfers"),
    )
    assert home_out.links == home_in.links == {"x-Home.Savings-20200115-5"}
    assert not office.links
    assert office.postings[0].flag == FLAG_WARNING


def test_different_days_are_not_matched():
    txns = link([transfer("2020-01-15", -100), transfer("2020-01-16", 100)])
    assert all(not txn.links for txn in txns)
    assert all(txn.postings[0].flag == FLAG_WARNING for txn in txns)


def test_wider_window_matches_what_tighter_one_misses():
    linker = Linker("Assets:Transfers", windows=[("%Y%m%d", None), ("%Y%m", None)])
    out, inn = link([transfer("2020-01-15", -100), transfer("2020-01-20", 100)], linker)
    assert out.links == inn.links == {"x-Transfers-202001-100"}


def test_tighter_window_takes_precedence():
    linker = Linker("Assets:Transfers", windows=[("%Y%m%d", None), ("%Y%m", None)])
    txns = link(
        [
            transfer("2020-01-15", -100),
            transfer("2020-01-15", 100),
            transfer("2020-01-20", -100),
            transfer("2020-01-20", 100),
        ],
        linker,
    )
    assert [txn.links for txn in txns] == [
        {"x-Transfers-20200115-100"},
        {"x-Transfers-20200115-100"},
        {"x-Transfers-20200120-100"},
        {"x-Transfers-20200120-100"},
    ]


WEEK = "%Yw%W"
SHIFT = datetime.timedelta(days=3)


def test_equally_wide_windows_with_opposite_offsets_cover_different_boundaries():
    linker = Linker("Assets:Transfers", windows=[(WEEK, None), (WEEK, SHIFT), (WEEK, -SHIFT)])
    txns = link(
        [
            transfer("2020-01-13", -100),  # Mon and Wed: same week
            transfer("2020-01-15", 100),
            transfer("2020-01-16", -200),  # Thu -> Mon: only the -3 day shift pairs these
            transfer("2020-01-20", 200),
        ],
        linker,
    )
    assert [txn.links for txn in txns] == [
        {"x-Transfers-2020w02-100"},
        {"x-Transfers-2020w02-100"},
        {"x-Transfers-2020w02-200"},
        {"x-Transfers-2020w02-200"},
    ]


def test_earlier_of_equally_wide_windows_decides_the_link():
    # Fri -> Mon falls in the same week under both a +3 and a -3 day shift.
    entries = [transfer("2020-01-17", -100), transfer("2020-01-20", 100)]
    plus_first = Linker("Assets:Transfers", windows=[(WEEK, SHIFT), (WEEK, -SHIFT)])
    minus_first = Linker("Assets:Transfers", windows=[(WEEK, -SHIFT), (WEEK, SHIFT)])
    assert {link for txn in link(entries, plus_first) for link in txn.links} == {
        "x-Transfers-2020w03-100"
    }
    assert {link for txn in link(entries, minus_first) for link in txn.links} == {
        "x-Transfers-2020w02-100"
    }


def test_date_offset_shifts_the_key_date():
    linker = Linker("Assets:Transfers", windows=[("%Y%m", datetime.timedelta(days=5))])
    out, inn = link([transfer("2020-01-28", -100), transfer("2020-02-02", 100)], linker)
    assert out.links == inn.links == {"x-Transfers-202002-100"}


def test_unbalanced_group_is_not_matched():
    linker = Linker("Assets:Transfers", include_amount=False)
    txns = link([transfer("2020-01-15", -100), transfer("2020-01-15", 90)], linker)
    assert all(not txn.links for txn in txns)
    assert all(txn.postings[0].flag == FLAG_WARNING for txn in txns)


def test_group_that_does_not_cancel_is_not_split_into_pairs():
    # Two -100s and one +100 share a key; no subset is matched.
    txns = link(
        [transfer("2020-01-15", -100), transfer("2020-01-15", -100), transfer("2020-01-15", 100)]
    )
    assert all(not txn.links for txn in txns)
    assert all(txn.postings[0].flag == FLAG_WARNING for txn in txns)


def test_mixed_currencies_are_not_matched():
    txns = link([transfer("2020-01-15", -100), transfer("2020-01-15", 100, currency="EUR")])
    assert all(not txn.links for txn in txns)
    assert all(txn.postings[0].flag == FLAG_WARNING for txn in txns)


def test_group_of_three_that_cancels_is_matched():
    linker = Linker("Assets:Transfers", windows=[("%Y%m", None)], include_amount=False)
    txns = link(
        [transfer("2020-01-02", -100), transfer("2020-01-10", 60), transfer("2020-01-20", 40)],
        linker,
    )
    assert all(txn.links == {"x-Transfers-202001"} for txn in txns)
    assert all(txn.postings[0].flag == FLAG_OKAY for txn in txns)


def test_manual_link_groups_transactions():
    out, inn = link(
        [
            transfer("2020-01-15", -100, links=["x-manual"]),
            transfer("2020-02-20", 100, links=["x-manual", "other"]),
        ]
    )
    assert out.links == {"x-manual"}
    assert inn.links == {"x-manual", "other"}
    assert out.postings[0].flag == inn.postings[0].flag == FLAG_OKAY


def test_unbalanced_manual_link_is_not_matched_by_other_keys():
    out, inn = link(
        [
            transfer("2020-01-15", -100, links=["x-manual"]),
            transfer("2020-01-15", 100),
        ]
    )
    assert out.links == {"x-manual"}
    assert not inn.links
    assert out.postings[0].flag == inn.postings[0].flag == FLAG_WARNING


def test_links_with_other_prefixes_are_ignored():
    out, inn = link(
        [
            transfer("2020-01-15", -100, links=["y-other"]),
            transfer("2020-01-15", 100),
        ]
    )
    assert out.links == {"y-other", "x-Transfers-20200115-100"}
    assert inn.links == {"x-Transfers-20200115-100"}


def test_linkable_accounts():
    assert LINKER.is_linkable("Assets:Transfers")
    assert LINKER.is_linkable("Assets:Transfers:Savings")
    assert not LINKER.is_linkable("Assets:TransfersOld")


def test_multiple_linkable_postings_is_an_error():
    txn = T(
        "2020-01-15",
        postings=[
            P("Assets:Transfers", A(-100, "USD")),
            P("Assets:Transfers:Savings", A(30, "USD")),
            P("Assets:Checking", A(70, "USD")),
        ],
    )
    new_entries, errors = LINKER([txn, transfer("2020-01-15", 100)], options())
    [error] = errors
    assert "2 postings to Assets:Transfers" in error.message
    assert error.entry == txn
    new_txn, other = new_entries
    assert not new_txn.links
    assert [p.flag for p in new_txn.postings] == [FLAG_WARNING, FLAG_WARNING, None]
    assert other.postings[0].flag == FLAG_WARNING


def test_other_entries_are_untouched_and_input_is_not_mutated():
    balance = B("2020-01-01", "Assets:Checking", A(0, "USD"))
    unrelated = T("2020-01-15", postings=[P("Assets:Checking", A(-5, "USD"))])
    entries = [balance, unrelated, transfer("2020-01-15", -100), transfer("2020-01-15", 100)]
    snapshot = copy.deepcopy(entries)
    new_entries = link(entries)
    assert entries == snapshot
    assert new_entries[:2] == [balance, unrelated]


def test_linking_is_idempotent():
    entries = [transfer("2020-01-15", -100), transfer("2020-01-15", 100), transfer("2020-01-16", 5)]
    once = link(entries)
    assert link(once) == once
