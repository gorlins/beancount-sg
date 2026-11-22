import datetime
import html
import re

import pytest
from fava.application import create_app

import beancount_sg.ext.summary as summary_ext

from ..test_summary import LEDGER as CONTENTS_LEDGER

ENABLE = 'custom "fava-extension" "beancount_sg.ext.summary"'
LEDGER = (
    f"""
option "title" "Test"
option "operating_currency" "USD"
2020-01-01 {ENABLE}
"""
    + CONTENTS_LEDGER
)


@pytest.fixture(autouse=True)
def today(monkeypatch):
    day = datetime.date(2024, 12, 31)
    monkeypatch.setattr(summary_ext, "local_today", lambda: day)
    return day


def get(tmp_path, path="", text=LEDGER):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(text)
    return (
        create_app([ledger], load=True)
        .test_client()
        .get(f"/test/extension/FinancialSummary/{path}")
    )


def text(body):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))


def page(tmp_path, ledger=LEDGER):
    response = get(tmp_path, text=ledger)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_totals(tmp_path):
    found = text(page(tmp_path))
    # 3,580 in checking and the 300,000 home; 199,000 on the mortgage and 100 on the card.
    assert "Everything we own 303,580.00 USD" in found
    assert "Everything we owe 199,100.00 USD" in found
    assert "Net worth 104,480.00 USD" in found


def test_accounts_by_group(tmp_path):
    found = text(page(tmp_path))
    assert "Bank accounts and cash Account Number Open since Balance Bank › Checking •••• 4321" in (
        found
    )
    assert "Loans and credit cards Account Number Open since Owed CreditCard •••• 3456" in found
    assert "Home › Mortgage 2020-01-01 199,000.00 USD" in found
    assert "Closed accounts" in found
    assert "Bank › Old •••• 8802 2020-01-01 2024-06-30" in found


def test_secured_loans_and_bills(tmp_path):
    found = text(page(tmp_path))
    assert "Home Home › Mortgage 300,000.00 USD 199,000.00 USD 101,000.00 USD" in found
    assert "Electric CreditCard 2024-03-08 100.00 USD 220.00 USD (2 payments)" in found
    assert "CreditCard Bank › Checking 2024-02-25 420.00 USD 420.00 USD (1 payment)" in found


def test_the_download_link_bypasses_favas_router(tmp_path):
    assert '<a class="fs-download" href="pdf" download data-remote>' in page(tmp_path)


def test_pdf(tmp_path):
    response = get(tmp_path, "pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="financial-summary-2024-12-31.pdf"'
    )
    assert response.get_data().startswith(b"%PDF")


def test_sections_without_content_are_left_out(tmp_path):
    ledger = f"""
option "title" "Test"
option "operating_currency" "USD"
2020-01-01 {ENABLE}
2020-01-01 open Assets:Bank:Checking USD
"""
    found = text(page(tmp_path, ledger))
    assert "Bank accounts and cash" in found
    for absent in ("Loans secured by property", "Bills ", "Closed accounts"):
        assert absent not in found
    assert get(tmp_path, "pdf", ledger).status_code == 200
