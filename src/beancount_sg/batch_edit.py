"""Batch edits to transactions' payees and categories, in the ledger's files.

Batch editing independent of any front end (see ``beancount_sg.ext.batch_edit``
for the Fava report):

- `plan_edits` finds the transactions to edit and what would change for each:
  it combines `find_transactions` (payee and/or narration regexes),
  `new_payee` (a payee template) and `category_posting` (the category).
- `apply_edits` writes planned edits to the ledger's source files, through a
  backend: `FileBackend` (the default) edits the files directly; front ends can
  provide their own, e.g. to write through Fava.
- `rewrite_entry` is the text transformation underneath: it rewrites one
  transaction's source text.

The *category* of a transaction is the account of its posting to an income or
expense account (Beancount's ``is_income_statement_account``), e.g.
``Expenses:Coffee``. A transaction with postings to two or more such accounts is
a *split*: its category is shown as ``-SPLIT-`` and can't be changed, but its
payee can. One with none (e.g. a transfer) has no category.

Edits are made by parsing the transaction's text with autobean-refactor, a
lossless Beancount parser, changing only its payee and the category posting's
account, and printing it back: everything else stays exactly as written (other
strings, tags, links, comments, flags, metadata, spacing, line endings). Edits
never add or remove lines, so other entries' line numbers stay valid while a
batch is applied.

An empty or missing new payee or category means "no change". Batch edits can't
remove a payee or set it to an empty string; to do that, edit the transaction
directly (e.g. in Fava's editor, which the report's dates link to).
"""

from __future__ import annotations

import functools
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import lark
from autobean_refactor import models, parser, printer
from beancount.core.account_types import (
    DEFAULT_ACCOUNT_TYPES,
    AccountTypes,
    is_income_statement_account,
)
from beancount.core.data import Directive, Posting, Transaction

# How a split transaction's category is shown.
SPLIT = "-SPLIT-"


class EditError(ValueError):
    """An edit couldn't be made, e.g. its text wasn't found or the file changed."""


@dataclass(frozen=True)
class PlannedEdit:
    """A matching transaction and its new payee and category, if they change.

    ``payee`` and ``category`` are None (or empty) where nothing changes.
    """

    txn: Transaction
    payee: str | None = None
    category: str | None = None

    @property
    def changes(self) -> bool:
        return bool(self.payee or self.category)


def plan_edits(
    entries: Iterable[Directive],
    *,
    payee_regex: str = "",
    narration_regex: str = "",
    payee: str = "",
    category: str = "",
    account_types: AccountTypes = DEFAULT_ACCOUNT_TYPES,
) -> list[PlannedEdit]:
    """The matching transactions (see `find_transactions`) and what would change.

    ``payee`` is a template for the new payee (see `new_payee`), and ``category``
    the new category account; leave either empty to keep it as it is. A new value
    that's the same as the current one counts as no change, and so does a new
    category for a split transaction or one without a category. ``account_types``
    are the ledger's account root names (see `beancount.parser.options`).

    Raises:
        re.error: If a pattern is invalid.
    """
    edits = []
    for txn in find_transactions(entries, payee_regex, narration_regex):
        to_payee = new_payee(txn, payee)
        posting = category_posting(txn, account_types)
        edits.append(
            PlannedEdit(
                txn,
                payee=to_payee if to_payee and to_payee != txn.payee else None,
                category=(
                    category if category and posting and category != posting.account else None
                ),
            )
        )
    return edits


def find_transactions(
    entries: Iterable[Directive], payee_regex: str = "", narration_regex: str = ""
) -> list[Transaction]:
    """Transactions written in a source file whose payee and narration match.

    The patterns are case-insensitive and match from the start of the text, so
    use e.g. ``.*coffee`` to match anywhere. An empty pattern matches anything,
    but at least one is required: with neither, nothing is returned.

    Raises:
        re.error: If a pattern is invalid.
    """
    if not payee_regex and not narration_regex:
        return []
    payee = re.compile(payee_regex, re.IGNORECASE)
    narration = re.compile(narration_regex, re.IGNORECASE)
    return [
        entry
        for entry in entries
        if isinstance(entry, Transaction)
        and is_editable(entry)
        and payee.match(entry.payee or "")
        and narration.match(entry.narration or "")
    ]


def is_editable(entry: Directive) -> bool:
    """Whether an entry is in an existing source file, rather than generated by a plugin."""
    filename = entry.meta.get("filename")
    return bool(filename) and "lineno" in entry.meta and Path(filename).is_file()


def category_postings(
    txn: Transaction, account_types: AccountTypes = DEFAULT_ACCOUNT_TYPES
) -> list[Posting]:
    """The transaction's postings to income or expense accounts."""
    return [p for p in txn.postings if is_income_statement_account(p.account, account_types)]


def category_posting(
    txn: Transaction, account_types: AccountTypes = DEFAULT_ACCOUNT_TYPES
) -> Posting | None:
    """The transaction's category posting, unless it's a split or has none."""
    postings = category_postings(txn, account_types)
    return postings[0] if len(postings) == 1 else None


def current_category(
    txn: Transaction, account_types: AccountTypes = DEFAULT_ACCOUNT_TYPES
) -> str | None:
    """The transaction's category account, `SPLIT` for a split, or None if it has none."""
    postings = category_postings(txn, account_types)
    if len(postings) > 1:
        return SPLIT
    return postings[0].account if postings else None


def new_payee(txn: Transaction, template: str) -> str | None:
    """The payee ``template`` gives for ``txn``, or None if it can't be filled in.

    An empty template, or one that fills in to an empty string, also gives None,
    i.e. no change: a payee can't be removed this way (see the module docs).

    ``{key}`` placeholders are filled from the transaction's metadata, e.g.
    ``{plaid_payee}``, with Python format specs, e.g. ``{store:04}``; a
    transaction missing a key gets None. Use ``{{`` and ``}}`` for literal braces.
    """
    if not template:
        return None
    try:
        return template.format_map(txn.meta) or None
    except KeyError:
        return None


def rewrite_entry(
    text: str,
    txn: Transaction,
    *,
    payee: str | None = None,
    category: str | None = None,
    account_types: AccountTypes = DEFAULT_ACCOUNT_TYPES,
) -> str:
    """A transaction's source text with its payee and/or category changed.

    This only transforms text; see `apply_edits` to edit the source files.

    Args:
        text: The transaction's text in its source file, from its first line
            through at least its last posting.
        txn: The loaded transaction.
        payee: The new payee; empty or None keeps it. (A payee can't be removed;
            see the module docs.)
        category: The new account for the category posting; empty or None keeps
            it. Ignored for a split transaction or one without a category.
        account_types: The ledger's account root names.

    Raises:
        EditError: If ``text`` isn't the transaction (e.g. its file changed and
            the lines moved since it was loaded).
    """
    # The parser expects the transaction without a final line ending; keep it aside.
    body = text.rstrip("\r\n")
    ending = text[len(body) :]
    try:
        entry = _parser().parse(body, models.Transaction)
    except lark.exceptions.UnexpectedInput as error:
        raise EditError(_moved(txn, f"couldn't parse {body.splitlines()[0]!r}")) from error
    # Check the text is this transaction, not e.g. one the line numbers now point to.
    written = (entry.date, entry.payee, entry.narration)
    if written != (txn.date, txn.payee, txn.narration):
        raise EditError(_moved(txn, f"found {written}"))

    if payee and payee != txn.payee:
        entry.payee = payee

    posting = category_posting(txn, account_types)
    if category and posting is not None and category != posting.account:
        _written_posting(entry, txn, posting).account = category

    return printer.print_model(entry, io.StringIO()).getvalue() + ending


def _written_posting(
    entry: models.Transaction, txn: Transaction, posting: Posting
) -> models.Posting:
    """The parsed posting written on ``posting``'s line, checked to be the same posting.

    The posting is found by its own line number rather than its position, since
    plugins may have added or reordered the loaded transaction's postings.

    Raises:
        EditError: If ``posting`` has no line number (it wasn't read from a file,
            e.g. a plugin added it), or no posting on that line matches it.
    """
    if not posting.meta or "lineno" not in posting.meta:
        raise EditError(f"The posting to {posting.account} wasn't read from a file")
    line = posting.meta["lineno"] - txn.meta["lineno"]  # 0-based line within the entry
    for written in entry.postings:
        if entry.token_store.get_position(written.first_token).line != line:
            continue
        # An automatic posting has no written amount; any other has the loaded one.
        if posting.meta.get("__automatic__"):
            amount = (None, None)
        else:
            amount = (posting.units.number, posting.units.currency)
        if (written.account, (written.number, written.currency)) == (posting.account, amount):
            return written
    raise EditError(_moved(txn, f"not its posting to {posting.account}"))


class Backend(Protocol):
    """Reads and writes transactions' source text, e.g. directly or through Fava."""

    def read_entry(self, txn: Transaction) -> str:
        """The transaction's source text, from its first line through its last posting."""
        ...

    def write_entry(self, txn: Transaction, old: str, new: str) -> None:
        """Replace the transaction's text ``old`` with ``new``.

        Raises:
            EditError: If the text is no longer ``old``, e.g. the file changed.
        """
        ...


class FileBackend:
    """Reads and writes transactions directly in their source files.

    An entry's text is its lines from its first line through its last posting,
    found from their line numbers, exactly as in the file (with line endings).
    """

    def read_entry(self, txn: Transaction) -> str:
        path, start, end = _entry_span(txn)
        return "".join(_read_lines(path)[start:end])

    def write_entry(self, txn: Transaction, old: str, new: str) -> None:
        path, start, end = _entry_span(txn)
        lines = _read_lines(path)
        if "".join(lines[start:end]) != old:
            raise EditError(f"{path} changed while editing it")
        lines[start:end] = new.splitlines(keepends=True)
        with path.open("w", encoding="utf-8", newline="") as file:
            file.write("".join(lines))


@dataclass
class AppliedEdits:
    """What `apply_edits` changed, and the edits that failed with why."""

    changed: list[PlannedEdit] = field(default_factory=list)
    errors: list[tuple[PlannedEdit, str]] = field(default_factory=list)


def apply_edits(
    edits: Iterable[PlannedEdit],
    backend: Backend | None = None,
    *,
    account_types: AccountTypes = DEFAULT_ACCOUNT_TYPES,
) -> AppliedEdits:
    """Write the edits that change something to the ledger's source files.

    Each edit is applied on its own: one that fails (e.g. its file changed since
    it was loaded) is reported in the result, and the others still go ahead.
    ``account_types`` must be the ones the edits were planned with.
    """
    backend = backend or FileBackend()
    result = AppliedEdits()
    for edit in edits:
        if not edit.changes:
            continue
        try:
            old = backend.read_entry(edit.txn)
            new = rewrite_entry(
                old,
                edit.txn,
                payee=edit.payee,
                category=edit.category,
                account_types=account_types,
            )
            if new != old:
                backend.write_entry(edit.txn, old, new)
                result.changed.append(edit)
        except (EditError, OSError) as error:
            result.errors.append((edit, str(error)))
    return result


def _entry_span(txn: Transaction) -> tuple[Path, int, int]:
    """The transaction's file, and the slice of its lines from its first to last posting.

    Beancount's line numbers are 1-based, so the transaction's first line is at
    index ``lineno - 1``, and the slice ends just after the last posting's line,
    at index ``lineno`` of that posting.
    """
    linenos = [txn.meta["lineno"]] + [
        posting.meta["lineno"]
        for posting in txn.postings
        if posting.meta and "lineno" in posting.meta
    ]
    return Path(txn.meta["filename"]), txn.meta["lineno"] - 1, max(linenos)


def _read_lines(path: Path) -> list[str]:
    """The file's lines, each with its line ending (\\n or \\r\\n) as written."""
    with path.open(encoding="utf-8", newline="") as file:
        return file.read().splitlines(keepends=True)


def _moved(txn: Transaction, found: str) -> str:
    return (
        f"Expected the transaction dated {txn.date} at line {txn.meta['lineno']}, but "
        f"{found}; has the file changed since it was loaded?"
    )


@functools.cache
def _parser() -> parser.Parser:
    """autobean-refactor's parser, built once (building it compiles its grammar)."""
    return parser.Parser()
