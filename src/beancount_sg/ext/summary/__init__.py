"""A Fava report summarizing the household's finances for someone who doesn't use Beancount.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.summary"

The "Financial Summary" report is written for a spouse or family member taking
over the finances, e.g. in case of death: which real-world accounts exist and
what they're worth, the equity in a home or car with a loan on it, the bills to
keep paying, and the accounts that were closed. A "Download PDF" link gives the
same as a PDF to print or keep somewhere safe. See `beancount_sg.summary` for
what each section holds and the metadata it reads; its ``bean-summary`` command
makes the same PDF without Fava.

The report covers the whole ledger as of today, whatever Fava's filters.
"""

from __future__ import annotations

from fava.ext import FavaExtensionBase, extension_endpoint
from fava.util.date import local_today
from flask import Response

from beancount_sg.summary import GROUPS, Summary, summarize
from beancount_sg.summary.pdf import render


class FinancialSummary(FavaExtensionBase):
    """Fava report summarizing the finances for a non-technical reader."""

    report_title = "Financial Summary"
    groups = GROUPS

    def summary(self) -> Summary:
        """The summary of the whole ledger, as of today."""
        return summarize(self.ledger.all_entries, self.ledger.options, local_today())

    @extension_endpoint
    def pdf(self) -> Response:
        """The summary as a PDF, to download."""
        summary = self.summary()
        response = Response(render(summary), mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f'attachment; filename="financial-summary-{summary.date}.pdf"'
        )
        return response
