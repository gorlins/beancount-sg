"""Helpers for testing Beancount plugins against small inline ledgers."""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from typing import Any

from beancount import loader
from beancount.core.data import Directive, Transaction, filter_txns
from beancount.parser import printer

AUTO_ACCOUNTS = "beancount.plugins.auto_accounts"


def load(
    ledger: str, plugins: Sequence[str] = (), *, auto_open: bool = True
) -> tuple[list[Directive], dict[str, Any]]:
    """Load an inline ledger with the given plugins enabled.

    The ledger text is dedented, so it can be written as an indented triple-quoted
    string. With ``auto_open`` (the default), accounts are opened automatically.

    Raises:
        AssertionError: if loading produces any errors.
    """
    names = [AUTO_ACCOUNTS, *plugins] if auto_open else list(plugins)
    header = "".join(f'plugin "{name}"\n' for name in names)
    entries, errors, options_map = loader.load_string(header + textwrap.dedent(ledger))
    if errors:
        raise AssertionError("".join(printer.format_error(e) for e in errors))
    return entries, options_map


def load_txns(ledger: str, plugins: Sequence[str] = (), **kwargs: Any) -> list[Transaction]:
    """Load an inline ledger (see `load`) and return its transactions in date order."""
    entries, _ = load(ledger, plugins, **kwargs)
    return list(filter_txns(entries))


def posting_flags(txn: Transaction) -> list[str | None]:
    """The flags of a transaction's postings, in order."""
    return [posting.flag for posting in txn.postings]
