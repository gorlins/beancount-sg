"""Helpers for plugins that work one transaction at a time.

Most plugins look at each transaction on its own and either rewrite it or add
directives next to it. These helpers run that per-transaction function over the
ledger and return ``(entries, errors)``, so a plugin can return their result
directly. Directives other than transactions are passed through unchanged.

Use `map_transactions` when the function only rewrites the transaction, and
`flat_map_transactions` when it also adds or removes directives, or reports
errors. Anything the function needs from the rest of the ledger (e.g. existing
balance assertions) should be computed first and passed in, e.g. with
`functools.partial`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from beancount.core.data import BeancountError, Directive, Transaction


def map_transactions(
    entries: Iterable[Directive], fn: Callable[[Transaction], Transaction]
) -> tuple[list[Directive], list[BeancountError]]:
    """Replace each transaction with ``fn(transaction)``.

    ``fn`` returns the transaction unchanged, or a modified copy.
    """
    new_entries = [fn(entry) if isinstance(entry, Transaction) else entry for entry in entries]
    return new_entries, []


def flat_map_transactions(
    entries: Iterable[Directive],
    fn: Callable[[Transaction], tuple[Iterable[Directive], Iterable[BeancountError]]],
) -> tuple[list[Directive], list[BeancountError]]:
    """Replace each transaction with the directives ``fn`` returns for it.

    ``fn`` returns ``(directives, errors)``. The directives take the transaction's
    place, so ``[txn]`` keeps it as is, ``[txn, *more]`` adds directives after it,
    and ``[]`` drops it. Errors from every call are collected in order.
    """
    new_entries: list[Directive] = []
    errors: list[BeancountError] = []
    for entry in entries:
        if isinstance(entry, Transaction):
            directives, txn_errors = fn(entry)
            new_entries.extend(directives)
            errors.extend(txn_errors)
        else:
            new_entries.append(entry)
    return new_entries, errors
