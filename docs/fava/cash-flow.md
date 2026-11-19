# Cash Flow

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.cash_flow"
```

A cash-flow statement: where your cash came from and where it went, in operating, investing and
financing activities, reconciled with the change in your cash.

![Cash Flow report](images/cash-flow.png)

## The statement

Accounts are classified by their **cash-flow role**, using the same metadata and defaults as
[Beancount.io's cash-flow report](https://beancount.io/blog/2026/08/28/declare-cash-flow-roles-in-your-ledger),
on the account's `open` directive:

```beancount
2020-01-01 open Assets:MoneyMarket
  cash-flow-role: "cash"
```

- **Cash** (`cash`): the cash and equivalents whose change the statement explains. Moving money
  between cash accounts doesn't show up.
- **Operating, investing and financing** (`operating`, `investing`, `financing`): every other
  account's flows over the period are a line in its role's section, as its effect on cash: money
  in is positive (green), money out negative (red). Income and expenses are rolled up to their
  top-level category, e.g. `Expenses:Food`.

Without a declared role (a parent's applies to its subaccounts), assets named with Cash, Checking,
Savings or Bank are `cash`, other assets `investing`, liabilities and equity `financing`, and
income and expenses `operating`. An unknown role is reported, and the default used. The page's
"How accounts are classified" section lists each account's role and where it came from.

**Credit cards** are liabilities, so `financing` by default: spending on a card is operating
spending borrowed from the card, and paying it off repays it. Declare `cash-flow-role: "operating"`
on a card to keep it in operating, where card spending and payments net out.

## Reconciliation

The **Cash & cash equivalents** panel lists each cash account at the start and end of the period,
and reconciles them: cash at the start, plus the net change from the activities, is cash at the
end. Flows are valued at each transaction's date and cash at its market value at the start and
end, in the first `operating_currency`. If those differ, e.g. from exchange rates moving on cash
held in another currency, a **change in value** line shows the difference.

## Period and filters

The period is Fava's time filter, or this year to date without one. Fava's account and advanced
filters apply, as on Fava's own reports.

The chart shows each activity's flows per interval, from the chart's interval menu (e.g. monthly).
Click a bar's date for that interval, or part of a bar for the income statement (operating) or
balance sheet (investing and financing). Click a statement line or cash account for its account
page.
