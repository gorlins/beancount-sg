# Year in Review

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.year_end"
```

A year-end dashboard: net worth, income and spending, savings, the withdrawal rate, and debt
paydown, for up to five years.

![Year in Review report](images/year-in-review.png)

## Which years

Fava's time filter picks the years, always whole:

- **A single year** (e.g. `2024`, or a month in it): that year and the four before.
- **A range of years** (e.g. `2022 - 2024`): those years.
- **No time filter:** this year and the four before. This year is year-to-date.

At most five years are shown, the latest, starting with the first year that has income or
expenses. Fava's account and advanced filters apply, as on Fava's own reports, but balances
always include everything before the years shown.

Values are in the ledger's first `operating_currency`, rounded to whole units. Holdings are at
market value at each year's end, or at cost if they have no price yet. Income and expenses are at
their value on each transaction's date. Amounts that can't be converted, for lack of prices, are
left out and their currencies listed.

## The dashboard

- **Cards** across the top show the final year's headline metrics, each with its change from the
  previous year.
- **Charts** of net worth per year, or switched below it to assets and liabilities stacked (Fava
  can't draw net worth as a line over them), and of expenses by category.
- **Net worth** and **Income & savings** tables.
- **Expenses by category** and **Debt paydown** tables.

On narrower screens, the tables of five years stack rather than sit side by side.

Every change from the previous year has an arrow and a sign, in **green when it's good** and **red
when it's bad**: more net worth, income or savings is good, and so is less spending or debt. A
year-to-date year's income and spending aren't compared with whole years, and its spending ratios
use its spending so far, annualized. Click a bar's date to make that the final year.

## Metrics

| Metric | |
| --- | --- |
| **Net worth** | Assets minus liabilities (what's owed) at the year's end, in [groups](#net-worth-groups). |
| **Investable assets** | Cash and investments: what spending could be drawn from, unlike a home. |
| **Savings** | Income minus expenses. |
| **Savings rate** | Savings as a percentage of income. |
| **Withdrawal rate** | A year's expenses as a percentage of investable assets at its start: like a withdrawal rate in retirement, what share of your cash and investments a year's spending would take. |
| **Spending / net worth** | A year's expenses as a percentage of net worth at its start, which also counts property and debt. |
| **Emergency fund** | Cash at the year's end, in months of spending. |
| **Debt paid down** | Principal paid on loans in the final year. Interest is in expenses. |

Ratios to an amount that isn't positive aren't shown.

## Expenses by category

Expenses per year by top-level category (e.g. `Expenses:Food`, not its subaccounts), with each
category's share of the final year. Click an amount for the account's page for that year.

## Net worth groups

| Group | Accounts |
| --- | --- |
| **Cash** | Assets with the `cash` [cash-flow role](#cash-flow-roles). |
| **Investments** | Assets with any other role (usually `investing`), unless they're property. |
| **Property** | Assets you live in or use rather than invest, e.g. a home or a car. |
| **Debt** | Loans: liabilities with the `financing` role (the default), except credit cards. |
| **Other** | The remaining liabilities: credit cards without a declared role, and liabilities declared with another role, e.g. `operating`. |

The roles say how an account's money flows; the groups say what it's worth to you. So `operating`,
which marks everyday income and spending, matters here only for a liability: declaring a credit
card (or any liability) `operating` keeps it out of debt, in *other*.

An asset is **property** if its `open` directive (or a parent's) says `investable: FALSE`, or else
if a liability is opened under the matching account path, which is how a secured loan is usually
kept, e.g. `Assets:Home` and `Liabilities:Home:Mortgage`. `investable: TRUE` makes an asset an
investment whatever liabilities match it.

```beancount
2020-01-01 open Assets:Car
  investable: FALSE
```

**Credit cards** aren't counted as debt, since their balances are everyday spending, paid off
monthly, rather than loans being paid down: a liability without a declared role and named with
Card is in *other*. Declare `cash-flow-role: "financing"` on a card to count it as debt.

## Cash-flow roles

Accounts' roles use the same metadata and defaults as
[Beancount.io's cash-flow report](https://beancount.io/blog/2026/08/28/declare-cash-flow-roles-in-your-ledger),
on the account's `open` directive:

```beancount
2020-01-01 open Assets:Bank:CD
  cash-flow-role: "investing"
```

The roles are `cash`, `investing`, `financing` and `operating`; a declared role also applies to the
account's subaccounts. Without one, assets named with Cash, Checking, Savings or Bank are `cash`,
other assets `investing`, and liabilities `financing`. A declared value that isn't a role (e.g. a
typo) is reported as an error and ignored. The page's "How accounts are classified" section lists each account's group and why.
