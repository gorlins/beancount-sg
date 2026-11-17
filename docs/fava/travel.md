# Travel

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.travel"
```

Totals travel spending by trip and by expense category, and calls out travel spending that isn't
tagged with a trip.

![Travel report, with its chart as an icicle](images/travel.png)

## Trips

Travel spending is the expense postings of transactions tagged `#travel`, within the current Fava
filter. Refunds count negatively. A transaction's **trip** is its other tag, such as
`#miami-2025`: the trips are the tags that occur on `#travel` transactions.

```beancount
2025-02-01 * "Hotel" "Two nights" #travel #miami-2025
  Expenses:Travel:Lodging  400.00 USD
  Liabilities:CreditCard:Voyager
```

The [`tag_travel`](../../README.md#beancount_sgpluginstag_travel) plugin adds both tags from
`travel` events.

**Limitation:** a travel transaction should have only one tag besides `#travel`, its trip. Any other
tag, such as `#reimbursable`, would be read as a second trip. A transaction with several counts
towards the first, alphabetically, and the report lists it in a warning so it can be fixed.

## The report

- **Untagged travel:** the line above the chart says how much travel spending isn't tagged with a
  trip, linked to those transactions. It's shown as "no trip" in the chart and the table.
- **Chart:** the spending **By trip**, then expense account, or **By category** (expense account),
  then trip. The icicle view shows the hierarchy most clearly.
- **Table:** each trip's first and last dates, number of transactions and total.

Every click opens a Fava page filtered by tag, within the current filter:

- A trip, in the table or the chart, opens the income statement filtered to `#travel #<trip>`.
- "no trip" opens it filtered to `#travel` without any of the trip tags.
- An expense account in the chart opens the account's page, filtered to its trip's travel
  transactions, or to all `#travel` in the **By category** chart's upper levels.
