"""``bean-summary``: write a ledger's financial summary as a PDF, without Fava.

    bean-summary ledger.beancount
    bean-summary ledger.beancount --output summary.pdf --date 2026-12-31

The summary is as of today (or ``--date``), the same as the Financial Summary
report in Fava. It's written to ``financial-summary-<date>.pdf`` unless
``--output`` names another file. Errors in the ledger are reported, but don't
stop the summary.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from beancount import loader
from beancount.parser import printer

from . import summarize
from .pdf import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bean-summary",
        description="Write a ledger's financial summary, for a non-technical reader, as a PDF.",
    )
    parser.add_argument("ledger", type=Path, help="the Beancount ledger file")
    parser.add_argument(
        "-o", "--output", type=Path, help="the PDF to write (default: financial-summary-<date>.pdf)"
    )
    parser.add_argument(
        "-d",
        "--date",
        type=datetime.date.fromisoformat,
        default=datetime.date.today(),
        help="summarize as of this date, YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args(argv)
    if not args.ledger.is_file():
        parser.error(f"no such ledger: {args.ledger}")
    entries, errors, options = loader.load_file(str(args.ledger))
    if errors:
        printer.print_errors(errors, file=sys.stderr)
    output = args.output or Path(f"financial-summary-{args.date}.pdf")
    output.write_bytes(render(summarize(entries, options, args.date)))
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
