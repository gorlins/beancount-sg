"""A Fava report for batch editing transactions' payees and categories.

Enable it in the ledger:

    2020-01-01 custom "fava-extension" "beancount_sg.ext.batch_edit"

On the "Batch Edit" report, search for transactions (within the current Fava
filter) by payee and/or narration regex, and enter a new payee and/or category.
The table previews each matching transaction and what would change; click a
date to open the transaction. "Apply" then edits the source files.

- Regexes are case-insensitive and match from the start, e.g. ``coffee shop``
  or ``.*coffee`` to match anywhere.
- The new payee can use ``{key}`` placeholders filled from each transaction's
  metadata, e.g. ``{plaid_payee}``; transactions without the key keep their
  payee.
- The category is the account of the transaction's automatic posting (the one
  without a written amount).

See `beancount_sg.batch_edit` for the editing rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fava.beans.funcs import hash_entry
from fava.context import g
from fava.core.file import get_entry_slice
from fava.ext import FavaExtensionBase, extension_endpoint
from fava.helpers import FavaAPIError
from flask import Response, jsonify, request

from beancount_sg.batch_edit import PlannedEdit, automatic_posting, edit_source, plan_edits

# The report's search fields, passed as URL query parameters. Their names must not
# clash with Fava's own (e.g. ``account`` and ``filter`` filter the whole page).
FIELDS = ("payee_regex", "narration_regex", "new_payee", "new_category")


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

    def preview(self) -> Preview:
        """The planned edits for the current search, within the current Fava filter."""
        try:
            fields = self.fields()
            edits = plan_edits(
                g.filtered.entries,
                payee_regex=fields["payee_regex"],
                narration_regex=fields["narration_regex"],
                payee=fields["new_payee"],
                account=fields["new_category"],
            )
            return Preview(edits)
        except re.error as error:
            return Preview([], error=f"Invalid regex: {error}")

    @staticmethod
    def category(edit: PlannedEdit) -> str | None:
        """The transaction's current category."""
        posting = automatic_posting(edit.txn)
        return posting.account if posting else None

    @staticmethod
    def entry_hash(edit: PlannedEdit) -> str:
        return hash_entry(edit.txn)

    @extension_endpoint(methods=["POST"])
    def apply(self) -> Response:
        """Apply the current search's edits to the source files."""
        preview = self.preview()
        if preview.error:
            return jsonify({"changed": 0, "errors": [preview.error]})
        changed = 0
        errors = []
        for edit in preview.edits:
            if not edit.changes:
                continue
            try:
                current = get_entry_slice(edit.txn)
                new_source = edit_source(
                    current.slice, edit.txn, payee=edit.payee, account=edit.account
                )
                if new_source != current.slice:
                    self.ledger.file.save_entry_slice(
                        hash_entry(edit.txn), new_source, current.sha256sum
                    )
                    changed += 1
            except (ValueError, FavaAPIError) as error:
                errors.append(f"{edit.txn.date} {edit.txn.payee or edit.txn.narration}: {error}")
        return jsonify({"changed": changed, "errors": errors})
