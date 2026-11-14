from beancount.core.data import Open

from beancount_sg.plugins.uptodate_subaccounts import META_KEY, uptodate_subaccounts
from beancount_sg.testing import load

PLUGIN = "beancount_sg.plugins.uptodate_subaccounts"


def marked_accounts(ledger: str, plugins=(PLUGIN,)) -> dict[str, bool]:
    """Each opened account's up-to-date metadata, if it has any."""
    entries, _ = load(ledger, plugins, auto_open=False)
    return {
        e.account: e.meta[META_KEY] for e in entries if isinstance(e, Open) and META_KEY in e.meta
    }


def test_direct_subaccounts_of_a_marked_account_are_marked():
    assert marked_accounts("""
        2020-01-01 open Assets:Brokerage
          fava-uptodate-indication: TRUE
        2020-01-01 open Assets:Brokerage:VTI
        2020-01-01 open Assets:Brokerage:BND
        2020-01-01 open Assets:Checking
        2020-01-01 open Assets:Checking:Joint
        """) == {
        "Assets:Brokerage": True,
        "Assets:Brokerage:VTI": True,
        "Assets:Brokerage:BND": True,
    }


def test_deeper_descendants_follow_their_own_parent():
    assert marked_accounts("""
        2020-01-01 open Assets:Brokerage
          fava-uptodate-indication: TRUE
        2020-01-01 open Assets:Brokerage:IRA
        2020-01-01 open Assets:Brokerage:IRA:VTI
        2020-01-01 open Assets:Retirement
        2020-01-01 open Assets:Retirement:401k
          fava-uptodate-indication: TRUE
        2020-01-01 open Assets:Retirement:401k:Fund
        """) == {
        "Assets:Brokerage": True,
        "Assets:Brokerage:IRA": True,
        "Assets:Retirement:401k": True,
        "Assets:Retirement:401k:Fund": True,
    }


def test_subaccount_can_opt_out():
    assert marked_accounts("""
        2020-01-01 open Assets:Brokerage
          fava-uptodate-indication: TRUE
        2020-01-01 open Assets:Brokerage:VTI
        2020-01-01 open Assets:Brokerage:Legacy
          fava-uptodate-indication: FALSE
        """) == {
        "Assets:Brokerage": True,
        "Assets:Brokerage:VTI": True,
        "Assets:Brokerage:Legacy": False,
    }


def test_subaccount_opened_before_its_parent_is_marked():
    assert marked_accounts("""
        2019-06-01 open Assets:Brokerage:VTI
        2020-01-01 open Assets:Brokerage
          fava-uptodate-indication: TRUE
        """) == {"Assets:Brokerage": True, "Assets:Brokerage:VTI": True}


def test_input_is_not_mutated():
    entries, options_map = load(
        """
        2020-01-01 open Assets:Brokerage
          fava-uptodate-indication: TRUE
        2020-01-01 open Assets:Brokerage:VTI
        """,
        auto_open=False,
    )
    new_entries, errors = uptodate_subaccounts(entries, options_map)
    assert errors == []
    assert META_KEY not in entries[1].meta
    assert new_entries[1].meta[META_KEY] is True


def test_separate_loads_do_not_share_marked_accounts():
    marked_accounts("""
        2020-01-01 open Assets:Brokerage
          fava-uptodate-indication: TRUE
        """)
    assert (
        marked_accounts("""
        2020-01-01 open Assets:Brokerage
        2020-01-01 open Assets:Brokerage:VTI
        """)
        == {}
    )
