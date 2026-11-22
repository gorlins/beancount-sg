# Fava extensions

Reports added to [Fava](https://beancount.github.io/fava/) by `beancount-sg`. Install the package
with the `fava` extra (see the [main README](../../README.md#installation)), then enable each
extension with a `custom` directive in your ledger:

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.checkbook"
```

Each report then appears in Fava's sidebar. Most cover the transactions in Fava's current time,
account and filter selection; Update Status and Financial Summary cover the whole ledger.

| Extension | Report | |
| --- | --- | --- |
| [`beancount_sg.ext.checkbook`](checkbook.md) | Checkbook | Checks written, by number |
| [`beancount_sg.ext.batch_edit`](batch-edit.md) | Batch Edit | Change many transactions' payees and categories at once |
| [`beancount_sg.ext.rewards`](rewards.md) | Credit Card Rewards | Spending and rewards per card and category |
| [`beancount_sg.ext.update_status`](update-status.md) | Update Status | When each account was last balanced |
| [`beancount_sg.ext.travel`](travel.md) | Travel | Travel spending by trip and category |
| [`beancount_sg.ext.payees`](payees.md) | Payee Review | Payees likely miscategorized or duplicated |
| [`beancount_sg.ext.year_end`](year-in-review.md) | Year in Review | Year-end dashboard of key metrics |
| [`beancount_sg.ext.cash_flow`](cash-flow.md) | Cash Flow | Cash-flow statement by activity |
| [`beancount_sg.ext.summary`](summary.md) | Financial Summary | Accounts, equity and bills for a non-technical reader, as a PDF too |
