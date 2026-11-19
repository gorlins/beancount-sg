# Fava extensions

Reports added to [Fava](https://beancount.github.io/fava/) by `beancount-sg`. Install the package
with the `fava` extra (see the [main README](../../README.md#installation)), then enable each
extension with a `custom` directive in your ledger:

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.checkbook"
```

Each report then appears in Fava's sidebar. Most cover the transactions in Fava's current time,
account and filter selection; Update Status covers the whole ledger.

| Extension | Report | |
| --- | --- | --- |
| [`beancount_sg.ext.checkbook`](checkbook.md) | Checkbook | Checks written, by number |
| [`beancount_sg.ext.batch_edit`](batch-edit.md) | Batch Edit | Change many transactions' payees and categories at once |
| [`beancount_sg.ext.rewards`](rewards.md) | Credit Card Rewards | Spending and rewards per card and category |
| [`beancount_sg.ext.update_status`](update-status.md) | Update Status | When each account was last balanced |
| [`beancount_sg.ext.travel`](travel.md) | Travel | Travel spending by trip and category |
| [`beancount_sg.ext.payees`](payees.md) | Payee Review | Payees likely miscategorized or duplicated |

## Screenshots

The screenshots in [`images/`](images) are of [`example.beancount`](example.beancount). After
changing a report's page, regenerate them from the repository root:

```bash
uv run --with playwright python docs/fava/screenshots.py
```

If Playwright has no browser installed yet, first run
`uv run --with playwright playwright install chromium`.
