# Cash Flow

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.cash_flow"
```

A cash-flow statement: where your cash came from and where it went, in operating, investing and
financing activities, reconciled with the change in your cash.

![Cash Flow report](images/cash-flow.png)

## The cards

The cards name each section's total in plain terms, with how it's made up below:

| Card | Section | |
| --- | --- | --- |
| **Net income** | Operating | Income minus spending: positive is a surplus, negative a deficit. |
| **Invested**, or **Withdrawn from investments** | Investing | Money put into investments minus money taken out, named for whichever was larger. |
| **Debt paid down**, or **Borrowed** | Financing | Loan and card payments minus new borrowing, named for whichever was larger. |
| **Change in cash** | | Cash at the end minus cash at the start. |
| **Emergency fund** | | Cash at the end, in months of spending (see below). |

Only net income is colored, green for a surplus and red for a deficit, since that's clearly good
or bad. Investing and financing aren't: investing or paying down debt is usually good, though it
takes money out of cash.

## Where cash came from and went

A Sankey diagram of the totals, balanced like the accounting equation. On the left is what brought
money into cash: **income**, and, if they went that way, money **withdrawn from investments** and
**borrowed**. On the right is where it went: **expenses**, money **invested**, and **debt paid
down**. If cash grew, **net cash saved** is on the right; if it shrank, **net cash drawn** is on
the left, so the two sides match. In the middle is the period's total **cash flow**. Investing and
debt are net, like the cards: a card balance that grew only shrinks the debt paid down.

Each band fades from its source's color to its target's. Click income or expenses for Fava's
income statement, or investing or debt for its balance sheet, for the period. The diagram is drawn
with [ECharts](https://echarts.apache.org), loaded from a CDN: the latest 6.x release, unless the
ledger sets another URL for all its reports, e.g. to pin a version:

```beancount
2020-01-01 custom "beancount-sg-option" "echarts-url" "https://cdn.jsdelivr.net/npm/echarts@6.1.0/dist/echarts.esm.min.mjs"
```

## The statement

The statement reads the same way as the cards. Each section's lines and total are in its own
direction:

| Section | Positive | Negative | Total |
| --- | --- | --- | --- |
| **Operating** | income | spending | Net income |
| **Investing** | money put into investments | money taken out | Invested |
| **Financing** | payments on loans and cards | new borrowing | Debt paid down |

So the change in cash is net income, minus invested, minus debt paid down.

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
  account's flows over the period are a line in its role's section. Income and expenses are
  rolled up to their top-level category, e.g. `Expenses:Food`.

Without a declared role (a parent's applies to its subaccounts), assets named with Cash, Checking,
Savings or Bank are `cash`, other assets `investing`, liabilities and equity `financing`, and
income and expenses `operating`, except debt-payment accounts (see below), which are `financing`. A
declared value that isn't a role (e.g. a typo) is reported as
an error and ignored. The page's "How accounts are classified" section lists each account's role
and where it came from.

**Credit cards** are `financing`, like any liability. Spending on a card is in operating, by
expense category, and the card's line in financing is only its net change over the period:
charges minus payments. A card paid in full each month nets to about zero; one carrying a balance
shows as borrowing, or as repaying it.

**Capital gains, dividends and interest** are income accounts, so by default they're in operating
and net income. When they stay invested, that overstates net income and the amount invested by the
same amount: e.g. a retirement plan rollover that sells funds and buys them again shows years of
gains as income, then as invested. Declare such accounts `investing`, and their lines move to the
investing section, where they net against the investment accounts they were earned in:

```beancount
2020-01-01 open Income:Retirement:Gains
  cash-flow-role: "investing"
```

For the rollover, net income is then just your income and spending, and invested is what actually
went in. The change in cash is the same either way. Gains in a taxable account are a choice:
declare them `investing` if they stay invested, or leave them in net income if you spend them. The
[Year in Review](year-in-review.md) reads the same declarations, counting such accounts as
investment returns rather than income.

**Debt-payment accounts**, e.g. an expense account that card or loan payments pass through on
their way from checking to the debt, are `financing`: both legs are in financing, next to the debt,
and a payment that reaches the loan in a later period doesn't show as spending meanwhile. Accounts
whose names say so are `financing` without a declaration: names containing Repayment, or Payment
after Loan, Mortgage or Card, such as `Expenses:CreditCardPayment` or `Expenses:Mortgage:Payment`
(but not `Expenses:Rent:Payment`). Declare any other `financing`.

## Reconciliation

The **Cash & cash equivalents** panel lists each cash account at the start and end of the period,
and reconciles them: cash at the start, plus the change from net income, investing and debt, is
cash at the end. Flows are valued at each transaction's date and cash at its market value at the start and
end, in the first `operating_currency`. If those differ, e.g. from exchange rates moving on cash
held in another currency, a **change in value** line shows the difference.

## Emergency fund

How many months of spending your cash covers: cash at the end of the period, divided by average
monthly spending (expenses) over the 12 months up to it. It uses 12 months whatever the period, so
a month's filter or a year-to-date year doesn't make it seasonal.

## Period and filters

The period is Fava's time filter, or the last 12 months (this month to date and the 11 before it)
without one. A time filter ends today at the latest, so this year is year-to-date. Fava's account
and advanced filters apply, as on Fava's own reports.

The charts show each card's amount per interval, from the chart's interval menu (e.g. monthly):
switch between net income, invested, debt paid down and the change in cash below the chart. Click
a bar's date for that interval, and a statement line or cash account for its account page.
