"""A Fava report for batch editing transactions' payees and categories.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.batch_edit"

On the "Batch Edit" report, search for transactions (within the current Fava
filter) by payee and/or narration regex, and enter a new payee and/or category.
The table previews each matching transaction and what would change; click a
date to open the transaction. "Apply" then edits the source files.

The page itself is static: its script loads the preview from the ``preview``
endpoint and applies edits with the ``apply`` endpoint, passing the search
fields along with the page's own URL parameters (Fava's filters). The search is
kept in the page's URL, so it survives reloads and navigation. After applying,
the page lists the edited transactions as they now are, since they often no
longer match the search that found them (e.g. after changing their payee).

- Regexes are case-insensitive and match from the start, e.g. ``coffee shop``
  or ``.*coffee`` to match anywhere.
- The new payee can use ``{key}`` placeholders filled from each transaction's
  metadata, e.g. ``{plaid_payee}``; transactions without the key keep their
  payee.
- The category is the transaction's income or expense account. A split
  transaction (two or more) shows ``-SPLIT-``; its payee can be changed, but not
  its category.

See `beancount_sg.batch_edit` for the editing rules.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from beancount.core.account_types import AccountTypes
from beancount.core.data import Transaction
from beancount.parser.options import get_account_types
from fava.beans.funcs import hash_entry
from fava.context import g
from fava.core import FavaLedger
from fava.core.file import get_entry_slice
from fava.ext import FavaExtensionBase, extension_endpoint
from fava.helpers import FavaAPIError
from flask import request

from beancount_sg.batch_edit import (
    EditError,
    PlannedEdit,
    apply_edits,
    current_category,
    plan_edits,
)

# The report's search fields, passed as URL query parameters. Their names must not
# clash with Fava's own (e.g. ``account`` and ``filter`` filter the whole page).
FIELDS = ("payee_regex", "narration_regex", "new_payee", "new_category")


@dataclass(frozen=True)
class Applied:
    """The transactions an apply edited, reloaded from their files, and its errors."""

    transactions: list[Transaction]
    errors: list[str]


@dataclass(frozen=True)
class Preview:
    """The edits a search would make, or why it can't be run."""

    edits: list[PlannedEdit]
    error: str | None = None

    @property
    def changes(self) -> int:
        return sum(edit.changes for edit in self.edits)


class BatchEdit(FavaExtensionBase):
    """Fava report for batch editing payees and categories."""

    report_title = "Batch Edit"
    has_js_module = True

    def fields(self) -> dict[str, str]:
        """The search fields from the current request."""
        return {field: request.args.get(field, "") for field in FIELDS}

    def plan(self) -> Preview:
        """The planned edits for the request's search, within its Fava filter."""
        try:
            fields = self.fields()
            edits = plan_edits(
                g.filtered.entries,
                account_types=self.account_types(),
                payee_regex=fields["payee_regex"],
                narration_regex=fields["narration_regex"],
                payee=fields["new_payee"],
                category=fields["new_category"],
            )
            return Preview(edits)
        except re.error as error:
            return Preview([], error=f"Invalid regex: {error}")

    def current_category(self, txn: Transaction) -> str | None:
        """The transaction's category account, ``-SPLIT-``, or None."""
        return current_category(txn, self.account_types())

    def account_types(self) -> AccountTypes:
        """The ledger's account root names."""
        return get_account_types(self.ledger.options)

    @staticmethod
    def entry_hash(txn: Transaction) -> str:
        """Fava's id for the transaction, to link to it."""
        return hash_entry(txn)

    @extension_endpoint
    def preview(self) -> str:
        """The preview table for the request's search, as an HTML fragment."""
        template = self.jinja_env.get_template("BatchEditPreview.html")
        return template.render(extension=self, preview=self.plan())

    @extension_endpoint(methods=["POST"])
    def apply(self) -> str:
        """Apply the request's search's edits; the edited transactions as an HTML fragment."""
        template = self.jinja_env.get_template("BatchEditApplied.html")
        preview = self.plan()
        if preview.error:
            return template.render(extension=self, applied=Applied([], [preview.error]))
        result = apply_edits(
            preview.edits, FavaBackend(self.ledger), account_types=self.account_types()
        )
        errors = [
            f"{edit.txn.date} {edit.txn.payee or edit.txn.narration}: {error}"
            for edit, error in result.errors
        ]
        return template.render(
            extension=self, applied=Applied(self._reloaded(result.changed), errors)
        )

    def _reloaded(self, edits: list[PlannedEdit]) -> list[Transaction]:
        """The edited transactions as they are now, from the reloaded ledger.

        Edits never change how many lines a transaction has, so each one is still
        at its file and line.
        """
        if not edits:
            return []
        self.ledger.load_file()
        by_position = {
            (entry.meta.get("filename"), entry.meta.get("lineno")): entry
            for entry in self.ledger.all_entries
            if isinstance(entry, Transaction)
        }
        positions = [(edit.txn.meta["filename"], edit.txn.meta["lineno"]) for edit in edits]
        return [by_position[position] for position in positions if position in by_position]


class FavaBackend:
    """A `beancount_sg.batch_edit.Backend` that edits files through Fava.

    Writing through Fava's file module serialises writes with Fava's own edits,
    rejects text that changed on disk, and tells Fava to reload the ledger.
    """

    def __init__(self, ledger: FavaLedger) -> None:
        self.ledger = ledger

    def read_entry(self, txn: Transaction) -> str:
        return get_entry_slice(txn).slice

    def write_entry(self, txn: Transaction, old: str, new: str) -> None:
        # Fava identifies the expected current text by its SHA-256, as get_entry_slice does.
        sha256sum = hashlib.sha256(old.encode("utf-8")).hexdigest()
        try:
            self.ledger.file.save_entry_slice(hash_entry(txn), new, sha256sum)
        except FavaAPIError as error:
            raise EditError(str(error)) from error
