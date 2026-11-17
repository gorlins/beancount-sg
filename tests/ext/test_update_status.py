import datetime
import html
import re

from beancount import loader
from beancount.core.data import Balance
from fava.application import create_app
from fava.beans.funcs import hash_entry
from fava.core import FavaLedger

from beancount_sg.builders import A
from beancount_sg.ext.update_status import account_statuses

LEDGER = """
option "title" "Test"
2020-01-01 custom "fava-extension" "beancount_sg.ext.update_status"

2020-01-01 open Equity:Opening
2020-01-01 open Expenses:Food
2020-01-01 open Assets:Checking USD
  fava-uptodate-indication: TRUE
2020-01-01 open Liabilities:Card USD
  fava-uptodate-indication: TRUE
2020-01-01 open Assets:Brokerage:VTI VTI
  fava-uptodate-indication: TRUE
2020-01-01 open Assets:Old USD
  fava-uptodate-indication: TRUE
2020-01-01 open Assets:Untracked USD

2024-01-01 * "Opening"
  Assets:Checking  1000.00 USD
  Assets:Brokerage:VTI  3 VTI
  Equity:Opening  -1000.00 USD
  Equity:Opening  -3 VTI

2024-02-01 balance Assets:Checking  1000.00 USD

2024-02-10 * "Groceries"
  Liabilities:Card  -50.00 USD
  Expenses:Food

2024-03-01 balance Assets:Checking  1000.00 USD
2024-03-01 balance Liabilities:Card  -50.00 USD

2024-03-05 * "Lunch"
  Assets:Checking  -20.00 USD
  Expenses:Food

2024-04-01 balance Assets:Brokerage:VTI  2 VTI

2024-05-01 close Assets:Old
"""


def statuses(text=LEDGER):
    entries, _, _ = loader.load_string(text)
    return {status.account: status for status in account_statuses(entries)}, entries


def test_only_open_tracked_accounts_are_listed():
    found, _ = statuses()
    assert list(found) == ["Assets:Brokerage:VTI", "Assets:Checking", "Liabilities:Card"]


def test_last_passing_balance_and_current_balance():
    found, _ = statuses()
    checking = found["Assets:Checking"]
    assert checking.balanced_as_of == datetime.date(2024, 3, 1)
    assert isinstance(checking.last_balance, Balance)
    assert checking.balance == [A("980.00", "USD")]
    assert checking.days_since_balanced(datetime.date(2024, 3, 11)) == 10
    assert checking.change == [A("-20.00", "USD")]
    card = found["Liabilities:Card"]
    assert card.balance == [A("-50.00", "USD")]
    assert card.change == []


def test_failing_balances_dont_count_and_never_balanced_uses_the_open_date():
    found, _ = statuses()
    vti = found["Assets:Brokerage:VTI"]
    assert vti.last_balance is None
    assert vti.balanced_as_of == datetime.date(2020, 1, 1)
    assert vti.balance == [A("3", "VTI")]
    assert vti.change == [A("3", "VTI")]


def test_change_is_per_currency():
    found, _ = statuses("""
2020-01-01 open Equity:Opening
2020-01-01 open Assets:Wallet
  fava-uptodate-indication: TRUE

2024-01-01 * "Opening"
  Assets:Wallet  100 USD
  Assets:Wallet  50 EUR
  Equity:Opening  -100 USD
  Equity:Opening  -50 EUR

2024-02-01 balance Assets:Wallet  100 USD
2024-01-15 balance Assets:Wallet  50 EUR

2024-02-05 * "Spend"
  Assets:Wallet  -10 USD
  Assets:Wallet  -5 EUR
  Equity:Opening  10 USD
  Equity:Opening  5 EUR

2024-02-06 * "New currency"
  Assets:Wallet  7 GBP
  Equity:Opening  -7 GBP
""")
    wallet = found["Assets:Wallet"]
    assert wallet.balanced_as_of == datetime.date(2024, 2, 1)
    assert wallet.change == [A("-5", "EUR"), A("7", "GBP"), A("-10", "USD")]


def page(tmp_path, text=LEDGER, query=""):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(text)
    response = (
        create_app([ledger], load=True).test_client().get(f"/test/extension/UpdateStatus/{query}")
    )
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(body):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


def row(body, account):
    """The table row for an account."""
    [match] = re.findall(rf"<tr>(?:(?!</tr>).)*>{re.escape(account)}</a>.*?</tr>", body, re.DOTALL)
    return match


def test_page_lists_accounts_with_status_and_dates(tmp_path):
    body = page(tmp_path)
    assert "Up to date as of 2020-01-01" in text(body)
    checking = row(body, "Assets:Checking")
    assert 'class="status-indicator status-yellow"' in checking
    assert "2024-03-05" in checking  # last entry
    assert "980.00 USD" in checking  # balance
    assert "-20.00 USD" in checking  # change since the last passing assertion
    card = row(body, "Liabilities:Card")
    assert 'class="status-indicator status-green"' in card
    assert "USD" not in card  # no balance or change when green
    vti = row(body, "Assets:Brokerage:VTI")
    assert 'class="status-indicator status-red"' in vti
    assert "2020-01-01 (opened)" in text(vti)
    assert text(vti).strip().endswith("3 VTI 3 VTI")  # balance, and change since opening
    table = body[body.index("<table") : body.index("</table>")]
    assert "Assets:Untracked" not in table
    assert "Assets:Old" not in table


def test_dates_link_to_their_entries(tmp_path):
    body = page(tmp_path)
    entries = FavaLedger(str(tmp_path / "main.beancount")).all_entries
    balance = next(
        entry
        for entry in entries
        if isinstance(entry, Balance)
        and entry.account == "Assets:Checking"
        and entry.date == datetime.date(2024, 3, 1)
    )
    lunch = next(entry for entry in entries if getattr(entry, "narration", None) == "Lunch")
    checking = row(body, "Assets:Checking")
    assert f'<a href="#context-{hash_entry(balance)}">2024-03-01</a>' in checking
    assert f'<a href="#context-{hash_entry(lunch)}">2024-03-05</a>' in checking


def test_yellow_dot_copies_balance_directives(tmp_path):
    checking = html.unescape(row(page(tmp_path), "Assets:Checking"))
    [directives] = re.findall(r'data-clipboard-text="([^"]*)"', checking)
    assert re.search(r"balance Assets:Checking\s+980.00 USD", directives)


def test_up_to_date_as_of_is_the_oldest_balance(tmp_path):
    balanced = LEDGER + "2024-04-02 balance Assets:Brokerage:VTI  3 VTI\n"
    body = text(page(tmp_path, balanced))
    assert "Up to date as of 2024-03-01" in body


def test_ignores_fava_filters(tmp_path):
    body = text(page(tmp_path, query="?time=2023"))
    assert "Assets:Checking" in body
    assert "980.00 USD" in body


def test_without_tracked_accounts(tmp_path):
    body = page(tmp_path, LEDGER.replace("fava-uptodate-indication", "note"))
    assert "<table" not in body
    assert "No open accounts are tracked yet" in body
