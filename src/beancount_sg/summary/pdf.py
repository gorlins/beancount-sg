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
    Spacer,
    Table,
    TableStyle,
)

from . import GROUPS, Summary

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


def _table(
    header: list[str],
    rows: list[list[object]],
    widths: list[float],
    amounts: int = 1,
    *,
    bold_first: bool = False,
) -> Table:
    """A table, its last ``amounts`` columns right-aligned, and its first in bold if asked."""
    first = len(header) - amounts
    cells = []
    for row in rows:
        texts = [escape(str(value)) for value in row]
        if bold_first:
            texts[0] = f"<b>{texts[0]}</b>"
        cells.append(
            [Paragraph(text, AMOUNT if i >= first else BODY) for i, text in enumerate(texts)]
        )
    table = Table([header, *cells], colWidths=[WIDTH * share for share in widths], repeatRows=1)
    style = [*TABLE_STYLE, ("ALIGN", (first, 0), (-1, 0), "RIGHT")] if amounts else TABLE_STYLE
    table.setStyle(TableStyle(style))
    return table


def _section(title: str, note: str | None, table: Table) -> KeepTogether:
    """A heading, a note and a table, kept on one page where they fit."""
    parts = [Paragraph(title, STYLES["Heading2"])]
    if note:
        parts.append(Paragraph(note, SMALL))
    return KeepTogether([*parts, table])


def render(summary: Summary) -> bytes:
    """The PDF's bytes."""
    title, amounts = summary.title, summary.money
    story: list = [
        Paragraph(f"Financial summary: {escape(title)}", STYLES["Title"]),
        Paragraph(
            f"As of {summary.date}. Values are in {summary.currency or 'each currency'}, at "
            "market value where there are prices. Account numbers show only their last 4 "
            "digits.",
            SMALL,
        ),
        Spacer(1, 12),
        _table(
            ["", "Value"],
            [
                ["Everything we own (assets)", amounts(summary.assets)],
                ["Everything we owe (loans and credit cards)", amounts(summary.debts)],
                ["Net worth (owned minus owed)", amounts(summary.net_worth)],
            ],
            [0.6, 0.4],
        ),
    ]
    for group, column in GROUPS.items():
        items = summary.group(group)
        if items:
            rows = [
                [
                    _or_dash(i.institution),
                    i.label,
                    _or_dash(i.owner),
                    _number(i.number),
                    amounts(i.amount),
                ]
                for i in items
            ]
            story.append(
                _section(
                    group,
                    None,
                    _table(
                        ["Institution", "Account", "Owner", "Number", column],
                        rows,
                        [0.22, 0.24, 0.2, 0.13, 0.21],
                        bold_first=True,
                    ),
                )
            )
    if summary.secured_loans:
        rows = [
            [i.label, i.loan_labels, amounts(i.value), amounts(i.owed), amounts(i.equity)]
            for i in summary.secured_loans
        ]
        story.append(
            _section(
                "Loans secured by property",
                "Equity is what the property is worth, minus what's owed on it.",
                _table(
                    ["Property", "Loans", "Value", "Owed", "Equity"],
                    rows,
                    [0.2, 0.2, 0.2, 0.2, 0.2],
                    amounts=3,
                ),
            )
        )
    if summary.bills:
        rows = [
            [
                bill.name,
                bill.paid_from_labels,
                bill.last_paid or "never",
                amounts(bill.last_amount),
                f"{amounts(bill.yearly)} ({bill.payments} payment"
                f"{'' if bill.payments == 1 else 's'})",
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
        title=f"Financial summary: {title}",
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    ).build(story)
    return buffer.getvalue()
