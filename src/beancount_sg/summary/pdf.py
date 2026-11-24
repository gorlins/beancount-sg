"""The financial summary as a PDF, laid out with ReportLab, to print or keep safe."""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

from . import Property, Summary

STYLES = getSampleStyleSheet()
BODY, SMALL = STYLES["BodyText"], STYLES["Italic"]
AMOUNT = ParagraphStyle("Amount", parent=BODY, alignment=TA_RIGHT)
TABLE_STYLE = [
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.grey),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
]
WIDTH = LETTER[0] - 1.5 * inch


def _number(last4: str | None) -> str:
    return f"\u2022\u2022\u2022\u2022 {last4}" if last4 else ""


def _or_dash(text: str | None) -> str:
    return text or "\u2014"


class _Markup(str):
    """Text with ReportLab's paragraph markup, e.g. ``<b>`` or ``<br/>``, already escaped."""


def _table(
    header: list[str],
    rows: list[list[object]],
    widths: list[float],
    amounts: int = 1,
    *,
    bold_first: bool = False,
    bold_rows: tuple[int, ...] = (),
) -> Table:
    """A table: its last ``amounts`` columns right-aligned, and its first column, or the
    ``bold_rows``, in bold if asked."""
    first = len(header) - amounts
    cells = []
    for index, row in enumerate(rows):
        texts = [value if isinstance(value, _Markup) else escape(str(value)) for value in row]
        if index in bold_rows:
            texts = [f"<b>{text}</b>" if text else text for text in texts]
        elif bold_first:
            texts[0] = f"<b>{texts[0]}</b>"
        cells.append(
            [Paragraph(text, AMOUNT if i >= first else BODY) for i, text in enumerate(texts)]
        )
    table = Table([header, *cells], colWidths=[WIDTH * share for share in widths], repeatRows=1)
    style = [*TABLE_STYLE, ("ALIGN", (first, 0), (-1, 0), "RIGHT")] if amounts else TABLE_STYLE
    table.setStyle(TableStyle(style))
    return table


def _grouped_table(
    header: list[str], groups: list[tuple[str, list[list[object]]]], widths: list[float]
) -> Table:
    """A table of rows under headings, e.g. accounts by statement line: the institution in
    bold, the last column right-aligned."""
    cells: list[list[object]] = [header]
    style = [*TABLE_STYLE, ("ALIGN", (-1, 0), (-1, 0), "RIGHT")]
    for title, rows in groups:
        style += [
            ("SPAN", (0, len(cells)), (-1, len(cells))),
            ("BACKGROUND", (0, len(cells)), (-1, len(cells)), colors.HexColor("#dde4ee")),
        ]
        cells.append([Paragraph(f"<b>{escape(title)}</b>", BODY)] + [""] * (len(header) - 1))
        for row in rows:
            texts = [escape(str(value)) for value in row]
            texts[0] = f"<b>{texts[0]}</b>"
            last = len(texts) - 1
            cells.append(
                [Paragraph(text, AMOUNT if i == last else BODY) for i, text in enumerate(texts)]
            )
    table = Table(cells, colWidths=[WIDTH * share for share in widths], repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def _loans(item: Property) -> _Markup:
    """A property's loans: each lender and the last 4 digits of its number, a line each."""
    return _Markup(
        "<br/>".join(
            escape(
                " ".join(
                    filter(
                        None,
                        [
                            loan.account.institution or loan.account.label,
                            _number(loan.account.number),
                        ],
                    )
                )
            )
            for loan in item.loans
        )
        or "none"
    )


def _section(title: str, note: str | None, table: Table) -> KeepTogether:
    """A heading, a note and a table, kept on one page where they fit."""
    parts = [Paragraph(title, STYLES["Heading2"])]
    if note:
        parts.append(Paragraph(note, SMALL))
    return KeepTogether([*parts, table])


def render(summary: Summary) -> bytes:
    """The PDF's bytes."""
    title, money = summary.title, summary.money
    statement: list[list[object]] = [["Assets", ""]]
    bold = [0]
    for line, _, total in summary.lines(liability=False):
        statement.append([line.title, money(total)])
    statement.append(["Total assets", money(summary.assets)])
    bold.append(len(statement) - 1)
    statement.append(["Liabilities", ""])
    bold.append(len(statement) - 1)
    for line, _, total in summary.lines(liability=True):
        statement.append([line.title, money(total)])
    statement.append(["Total liabilities", money(summary.debts)])
    statement.append(["Net worth (total assets minus total liabilities)", money(summary.net_worth)])
    bold += [len(statement) - 2, len(statement) - 1]
    story: list = [
        Paragraph(f"Personal financial statement: {escape(title)}", STYLES["Title"]),
        Paragraph(
            f"As of {summary.date}. Laid out like the personal financial statement a bank asks "
            "for (SBA Form 413). Values are in "
            f"{summary.currency or 'each currency'}, at market value where there are prices. "
            "Account numbers show only their last 4 digits.",
            SMALL,
        ),
        _section(
            "Statement",
            None,
            _table(["", "Amount"], statement, [0.65, 0.35], bold_rows=tuple(bold)),
        ),
    ]
    for liability, title, column in ((False, "Assets", "Value"), (True, "Liabilities", "Owed")):
        groups = [
            (
                line.title,
                [
                    [
                        _or_dash(i.institution),
                        i.label,
                        _or_dash(i.owner),
                        _number(i.number),
                        money(i.amount),
                    ]
                    for i in items
                ],
            )
            for line, items, _ in summary.lines(liability)
        ]
        if groups:
            story.append(
                _section(
                    title,
                    None,
                    _grouped_table(
                        ["Institution", "Account", "Owner", "Number", column],
                        groups,
                        [0.22, 0.24, 0.2, 0.13, 0.21],
                    ),
                )
            )
    if summary.properties:
        rows = [
            [
                item.asset.label,
                _or_dash(item.asset.owner),
                money(item.value),
                _loans(item),
                money(item.owed),
                _Markup(
                    "<br/>".join(escape(money(loan.payments.last_amount)) for loan in item.loans)
                ),
                money(item.equity),
            ]
            for item in summary.properties
        ]
        story.append(
            _section(
                "Real estate and vehicles",
                "Each property, the loans against it, and the equity: its value minus what's owed.",
                _table(
                    ["Property", "Owner", "Value", "Loans", "Owed", "Last payment", "Equity"],
                    rows,
                    [0.12, 0.15, 0.14, 0.17, 0.14, 0.14, 0.14],
                    amounts=3,
                ),
            )
        )
    if summary.bills:
        rows = [
            [
                bill.name,
                bill.payments.paid_from_labels,
                bill.payments.last_paid or "never",
                money(bill.payments.last_amount),
                f"{money(bill.payments.yearly)} ({bill.payments.count} payment"
                f"{'' if bill.payments.count == 1 else 's'})",
            ]
            for bill in summary.bills
        ]
        story.append(
            _section(
                "Bills",
                "Regular payments to keep up, and the account each was last paid from.",
                _table(
                    ["Bill", "Paid from", "Last paid", "Last amount", "Last 12 months"],
                    rows,
                    [0.2, 0.2, 0.13, 0.17, 0.3],
                    amounts=2,
                ),
            )
        )
    if summary.closed_accounts:
        rows = [
            [
                _or_dash(i.institution),
                i.label,
                _or_dash(i.owner),
                _number(i.number),
                i.opened,
                i.closed,
            ]
            for i in summary.closed_accounts
        ]
        story.append(
            _section(
                "Closed accounts",
                "No longer in use: listed so they're recognized if they turn up.",
                _table(
                    ["Institution", "Account", "Owner", "Number", "Opened", "Closed"],
                    rows,
                    [0.19, 0.2, 0.17, 0.14, 0.15, 0.15],
                    amounts=0,
                ),
            )
        )
    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        title=f"Personal financial statement: {title}",
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    ).build(story)
    return buffer.getvalue()
