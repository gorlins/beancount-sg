# Fava extensions

Reports added to [Fava](https://beancount.github.io/fava/) by `beancount-sg`. Install the package
with the `fava` extra (see the [main README](../../README.md#installation)), then enable each
extension with a `custom` directive in your ledger:

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.checkbook"
```

Each report then appears in Fava's sidebar. Most cover the transactions in Fava's current time,
account and filter selection; Update Status covers the whole ledger, and Year in Review takes only
the time filter's last year.

| Extension | Report | |
| --- | --- | --- |
| [`beancount_sg.ext.checkbook`](checkbook.md) | Checkbook | Checks written, by number |
| [`beancount_sg.ext.batch_edit`](batch-edit.md) | Batch Edit | Change many transactions' payees and categories at once |
| [`beancount_sg.ext.rewards`](rewards.md) | Credit Card Rewards | Spending and rewards per card and category |
| [`beancount_sg.ext.update_status`](update-status.md) | Update Status | When each account was last balanced |
| [`beancount_sg.ext.travel`](travel.md) | Travel | Travel spending by trip and category |
| [`beancount_sg.ext.payees`](payees.md) | Payee Review | Payees likely miscategorized or duplicated |
| [`beancount_sg.ext.year_end`](year-in-review.md) | Year in Review | Year-end dashboard of key metrics |

## Screenshots

The screenshots in [`images/`](images) are of [`example.beancount`](example.beancount), or for
the Year in Review, which needs years of history, [`year-in-review.beancount`](year-in-review.beancount).
After changing a report's page, regenerate its screenshots from the repository root, by name, so
the other reports' screenshots don't change:

```bash
uv run --with playwright python docs/fava/screenshots.py year-in-review
```

Without names, it regenerates them all.

If Playwright has no browser installed yet, first run
`uv run --with playwright playwright install chromium`.
