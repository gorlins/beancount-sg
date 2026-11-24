# beancount-sg

Personal collection of Beancount plugins and Fava extensions. ("SG" is the author's initials.)

## Installation

This package is not published on PyPI; install it directly from GitHub:

```bash
pip install git+https://github.com/gorlins/beancount-sg.git
```

To use the Fava extensions, install with the `fava` extra:

```bash
pip install "beancount-sg[fava] @ git+https://github.com/gorlins/beancount-sg.git"
```

Pin to a tag, branch, or commit by appending `@<ref>`, e.g.
`git+https://github.com/gorlins/beancount-sg.git@v0.1.0`.

With uv:

```bash
uv add git+https://github.com/gorlins/beancount-sg.git
```

## Plugins

Beancount plugins live in `beancount_sg.plugins`; Fava extensions live in `beancount_sg.ext`.

### `beancount_sg.plugins.flag_balanced`

```beancount
plugin "beancount_sg.plugins.flag_balanced"
```

Flags postings by whether a balance assertion verifies them. For postings to accounts (and
currencies) that have their own `balance` assertions, it sets the posting flag to `*` if a later
assertion on that exact account covers it, and `!` otherwise. Other postings and all transaction
flags are left alone.

### `beancount_sg.plugins.flag_from_postings`

```beancount
plugin "beancount_sg.plugins.flag_from_postings"
```

Sets each transaction's flag from its postings: `!` if any posting is `!`, otherwise `*`.
Unflagged postings are ignored, and special transaction flags (e.g. `P`) are kept. List it after
any plugins that set posting flags, such as `flag_balanced`.

### `beancount_sg.plugins.link_bills`

```beancount
plugin "beancount_sg.plugins.link_bills" "Liabilities:Bills"
```

Links each month's bills and payments in the given account when they cancel out, flagging those
postings `*` if matched and `!` if not.

### `beancount_sg.plugins.link_transfers`

```beancount
plugin "beancount_sg.plugins.link_transfers" "Assets:Transfers"
```

Links same-amount transactions in the given account when they cancel out, such as the two sides
of a transfer, trying progressively wider date windows (same day, week, then month). Postings are
flagged like `link_bills`. Pair either with `flag_from_postings` to update transaction flags.

### `beancount_sg.plugins.close_positions`

```beancount
plugin "beancount_sg.plugins.close_positions"
```

For sales marked `closing: TRUE`, asserts the position is zero the next day, e.g. after selling all
shares of a stock or fund, and closes the account if it holds only that commodity.

### `beancount_sg.plugins.uptodate_subaccounts`

```beancount
plugin "beancount_sg.plugins.uptodate_subaccounts"
```

Extends Fava's `fava-uptodate-indication` from an account to its direct subaccounts, e.g. to every
security under a brokerage account.

### `beancount_sg.plugins.add_check_numbers`

```beancount
plugin "beancount_sg.plugins.add_check_numbers"
```

Records the check number from narrations like `CHECK #1042` as `check-no` metadata on payments by
check. Converts older `check_no` and `checknum` metadata to `check-no`, with an error if the numbers
disagree.

### `beancount_sg.plugins.tag_recurring_payees`

```beancount
plugin "beancount_sg.plugins.tag_recurring_payees"
```

Once any transaction from a payee is tagged `#recurring` (or a configured tag), tags all of that
payee's transactions.

### `beancount_sg.plugins.tag_travel`

```beancount
plugin "beancount_sg.plugins.tag_travel" "{'travel_accounts': ['Expenses:Travel'], 'conditional_accounts': ['Expenses:Food']}"
```

Tags travel spending, and everyday spending while away (per `travel` events), with `#travel` and a
trip tag such as `#new-york-city-2024`.

## Fava extensions

These need the `fava` extra. See [`docs/fava`](docs/fava/README.md) for how to use each report,
with screenshots.

### `beancount_sg.ext.checkbook`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.checkbook"
```

A "Checkbook" report listing transactions with `check-no` metadata (see `add_check_numbers`): date,
number, payee, paying account, category and amount. [Docs](docs/fava/checkbook.md)

### `beancount_sg.ext.batch_edit`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.batch_edit"
```

A "Batch Edit" report: find transactions by payee and/or narration regex, preview new payees
(optionally from metadata, e.g. `{plaid_payee}`) and categories (income or expense accounts), then
apply them to the ledger files. Split transactions show `-SPLIT-` and keep their categories.
[Docs](docs/fava/batch-edit.md)

### `beancount_sg.ext.rewards`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.rewards"

2020-01-01 open Liabilities:CreditCard:Voyager USD
  rewards: "points"            ; or "cashback"
  rewards-rate: 1              ; default rate
  rewards-rate-dining: 3       ; per card issuer's category, from `category` metadata
  rewards-point-value: 0.0125  ; optional
```

A "Credit Card Rewards" report: each configured card's expense spending grouped by the card
issuer's category (`category` metadata), with its rate, rewards and cash value, plus charts of
spend and value by card and category. Categories link to the card's transactions in that category.
[Docs](docs/fava/rewards.md)

### `beancount_sg.ext.update_status`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.update_status"
```

An "Update Status" report of the accounts with Fava's `fava-uptodate-indication`: each one's
status, last entry, last balance assertion and its amount, the ledger's difference from it, and the
oldest of the balance dates. [Docs](docs/fava/update-status.md)

### `beancount_sg.ext.travel`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.travel"
```

A "Travel" report of `#travel` spending by trip (tags used only on travel transactions, e.g.
`#miami-2025`, as `tag_travel` adds) and expense category, as charts (including spending over time,
stacked by trip) and a table of trips, calling out travel spending without a trip. Every link opens Fava filtered by the trip's tag.
[Docs](docs/fava/travel.md)

### `beancount_sg.ext.payees`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.payees"
```

A "Payee Review" report of payees likely miscategorized (transactions in different income or expense
categories, mostly-one-category payees first) or duplicated (similar names, by
[rapidfuzz](https://github.com/rapidfuzz/RapidFuzz)), with links to their transactions and, with
Batch Edit enabled, to the fix. [Docs](docs/fava/payees.md)

### `beancount_sg.ext.year_end`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.year_end"
```

A "Year in Review" dashboard of up to five years, picked with Fava's time filter: net worth
(cash, investments, property, debt), income, expenses and savings rate, withdrawal rate, expenses
by top-level category, and debt paydown, with year-over-year changes. [Docs](docs/fava/year-in-review.md)

### `beancount_sg.ext.cash_flow`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.cash_flow"
```

A "Cash Flow" statement: each account's flows in operating, investing and financing activities,
reconciled with the change in cash, by `cash-flow-role` metadata or account names.
[Docs](docs/fava/cash-flow.md)

### `beancount_sg.ext.summary`

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.summary"
```

A "Financial Summary" for someone who doesn't use Beancount, e.g. a spouse taking over, laid out
like a bank's personal financial statement (SBA Form 413): assets and liabilities by line, each
account with its institution, owner and the last 4 digits of its number, real estate and vehicles
with their loans and equity, the bills marked with `bill` metadata, and closed accounts, with a PDF
to download. The `bean-summary` command makes the same PDF without Fava.
[Docs](docs/fava/summary.md)

## Utilities

### `beancount_sg.builders`

Concise constructors (`A`, `T`, `P`, `B`) for building amounts, transactions, postings and balance
assertions in importers, plugins and tests.

### `beancount_sg.plugins.plugin_helpers`

`map_transactions` and `flat_map_transactions` run a per-transaction function over a ledger, for
writing plugins that rewrite transactions or add directives next to them.

### `beancount_sg.cash_flow_roles`

Accounts' cash-flow roles (`cash`, `operating`, `investing`, `financing`) from `cash-flow-role`
metadata on their `open` directives, or their names: the convention Beancount.io's cash-flow report
uses, plus inheritance by subaccounts and `financing` for debt-payment accounts such as
`Expenses:CreditCardPayment`.

### `beancount_sg.ext.echarts`

[ECharts](https://echarts.apache.org) charts in Fava extension reports, for charts Fava doesn't
have (e.g. Sankey diagrams): a mixin that serves a browser helper, which loads ECharts from a CDN
(configurable), draws each chart from its option in the template, and loads its data from one of
the extension's endpoints.

### `beancount_sg.summary`

The financial summary behind the Financial Summary report, independent of Fava, and its PDF. The
`bean-summary` command, installed with the package, writes a ledger's summary as a PDF:

```bash
bean-summary ledger.beancount                       # financial-summary-<today>.pdf
bean-summary ledger.beancount -o summary.pdf -d 2026-12-31
```

### `beancount_sg.batch_edit`

The editing logic behind the Batch Edit report, independent of Fava: plan payee and category
changes for matching transactions and apply them to their source text.

### `beancount_sg.rewards`

The logic behind the Credit Card Rewards report, independent of Fava: read cards' rewards programs
from `open` metadata, and total spending and rewards per card and category.

## Development

```bash
uv sync            # create .venv and install the package + dev tools
uv run pytest      # run tests
uv run ruff check  # lint
uv run ruff format # format
```

Before committing, make sure `ruff check`, `ruff format --check` and `pytest` all pass; CI runs
them on every supported Python version.

Fava is an optional dependency (the `fava` extra), so code that imports `fava` must stay out of
modules that plugin-only users import.

Metadata keys are kebab-case, e.g. `check-no`, like Fava's own (`fava-uptodate-indication`).
Plugin and extension configs are Python dict literals, so their keys are snake_case like Python
names, e.g. `{'travel_accounts': [...]}`.

### Branches and pull requests

- Name branches after the change, with a type prefix: `feat/…`, `fix/…`, `ci/…`, `docs/…`,
  `build/…`.
- One logical change per branch and pull request, started from the latest `main`.
- Don't push directly to `main`.

### Releases

The version is derived from git tags, so it is never written in the code. To release, tag `main`
and push the tag:

```bash
git tag v0.2.0
git push origin v0.2.0
```

## License

Copyright (C) 2026 Scott Gorlin.

Licensed under the [GNU General Public License, version 2](LICENSE) only (GPL-2.0-only), like
Beancount itself.
