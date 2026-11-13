"""Helpers for testing Beancount plugins against small inline ledgers."""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from typing import Any

from beancount import loader
from beancount.core.data import Directive, Transaction, filter_txns
from beancount.parser import printer

AUTO_ACCOUNTS = "beancount.plugins.auto_accounts"


Plugin = str | tuple[str, str]


def load(
    ledger: str, plugins: Sequence[Plugin] = (), *, auto_open: bool = True
) -> tuple[list[Directive], dict[str, Any]]:
    """Load an inline ledger with the given plugins enabled.

    Plugins are module names, or ``(name, config)`` pairs for plugins that take a
    config string. The ledger text is dedented, so it can be written as an indented
    triple-quoted string. With ``auto_open`` (the default), accounts are opened
    automatically.

    Raises:
        AssertionError: if loading produces any errors.
    """
    plugins = [AUTO_ACCOUNTS, *plugins] if auto_open else list(plugins)
    header = "".join(_plugin_directive(plugin) for plugin in plugins)
    entries, errors, options_map = loader.load_string(header + textwrap.dedent(ledger))
    if errors:
        raise AssertionError("".join(printer.format_error(e) for e in errors))
    return entries, options_map


def load_txns(ledger: str, plugins: Sequence[Plugin] = (), **kwargs: Any) -> list[Transaction]:
    """Load an inline ledger (see `load`) and return its transactions in date order."""
    entries, _ = load(ledger, plugins, **kwargs)
    return list(filter_txns(entries))


def _plugin_directive(plugin: Plugin) -> str:
    if isinstance(plugin, str):
        return f'plugin "{plugin}"\n'
    name, config = plugin
    return f'plugin "{name}" "{config}"\n'
