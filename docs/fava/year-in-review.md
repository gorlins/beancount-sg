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
- **Expenses by category** and **Debt** tables.

On narrower screens, the tables of five years stack rather than sit side by side.

Every change from the previous year has an arrow and a sign, in **green when it's good** and **red
when it's bad**: more net worth, income or savings is good, and so is less spending or debt. Click
a bar's date to make that the final year.

## Metrics

Each metric is one of three kinds, which differ for the current, year-to-date year:

- **Balances** are at the year's end; for the current year, today.
- **Flows** are totals during the year; for the current year, so far. A year-to-date total isn't
  compared with whole years'.
- **Spending ratios** compare 12 months of spending with balances at the year's end. For a whole
  year, the 12 months are the year; for the current year, they're the last 12 months, so its
  ratios compare with whole years' (spending since January 1st would make them meaningless early in
  the year).

| Metric | Kind | |
| --- | --- | --- |
| **Net worth** | Balance | Assets minus liabilities (what's owed), in [groups](#net-worth-groups). |
| **Investable assets** | Balance | Cash and investments: what spending could be drawn from, unlike a home. |
| **Income**, **expenses** | Flow | Income and expense accounts, except [investment returns and transfers](#investment-returns-and-transfers). |
| **Savings** | Flow | Income minus expenses, wherever the money went: to a savings account, investments or paying down debt. |
| **Savings rate** | Flow | Savings as a percentage of income. As a ratio of two flows over the same months, it isn't annualized, and a year-to-date rate is compared with whole years'. |
| **Debt paid down** | Flow | The fall in what's owed on [debts](#net-worth-groups): payments minus new borrowing, so negative when debt grew. Interest is in expenses. |
| **Investment returns** | Flow | [Investment returns](#investment-returns-and-transfers), e.g. capital gains declared `investing`: not in income, expenses or savings. Shown only when there are any. |
| **Withdrawal rate** | Spending ratio | Spending as a percentage of investable assets: like a withdrawal rate in retirement, what share of your cash and investments a year's spending would take. |
| **Spending / net worth** | Spending ratio | Spending as a percentage of net worth, which also counts property and debt. |
| **Emergency fund** | Spending ratio | Cash, in months of average spending. |

Ratios to an amount that isn't positive aren't shown. The [Cash Flow](cash-flow.md) report covers
any period, by default the last 12 months.

## Expenses by category

Expenses per year by top-level category (e.g. `Expenses:Food`, not its subaccounts), with each
category's share of the final year. Click an amount for the account's page for that year.

## Debt

Each debt with a balance at the final year's start or end: what was owed then, and how much it was
paid down. Paid down is the net fall in the balance, so it works for revolving credit (a credit card
or HELOC) as well as a loan: a card paid in full each month comes to about zero, and one carrying a
balance shows it growing or being paid off.

## Net worth groups

| Group | Accounts |
| --- | --- |
| **Cash** | Cash and savings accounts: those with the `cash` [cash-flow role](#cash-flow-roles), except in a retirement account. |
| **Investments** | Other assets, unless they're property. |
| **Property** | Assets you live in or use rather than invest: real estate, vehicles and other personal property. |
| **Debt** | Liabilities with the `financing` role, the default: loans and credit cards. |
| **Other** | Liabilities declared with another role. |

An asset's group follows its line on the [Financial Summary](summary.md#which-line-an-account-is-on)'s
personal financial statement, so the two reports agree: the `real-estate`, `automobiles` and
`personal-property` lines are property, `cash` and `savings` are cash, and the rest are
investments. Most property needs no declaration: it's inferred from its name (e.g. Home, House,
Car) or a mortgage or vehicle loan opened under its path, e.g. `Liabilities:Home:Mortgage` for
`Assets:Home`. A margin loan under `Assets:Brokerage` doesn't make the brokerage property.
Investable assets leave property out, though net worth still counts it.

Declare anything else with `asset-type`, on the account's `open` directive (it also applies to
subaccounts), or on the `commodity` directive of what it holds:

```beancount
2020-01-01 open Assets:Collectibles
  asset-type: "personal-property"
```

## Investment returns and transfers

Capital gains, dividends and interest are income in Beancount, so by default they count as income
and savings here. That overstates both when the money never reached you: e.g. a retirement plan
rollover that sells funds in one plan and buys them again in another realizes years of gains at
once, though nothing was earned or spent.

Declare such accounts with the `investing` [cash-flow role](#cash-flow-roles), and they're
**investment returns** instead:

```beancount
2020-01-01 open Income:Retirement:Gains
  cash-flow-role: "investing"
```

Investment returns are left out of income, expenses, savings, the savings rate and the spending
ratios, and shown on their own row. Net worth is unchanged: the gains are in your investments'
value either way. A role on a parent account (e.g. `Income:CapitalGains`) applies to its
subaccounts, and an expense account can be declared the same way, e.g. fees paid out of an
investment account.

Gains in a taxable account are a choice: declare them `investing` if they stay invested, or leave
them as income if you spend them. Keeping retirement-plan gains, dividends and interest in their
own accounts makes the choice per account.

Income and expense accounts with another role, e.g. `financing`, are **transfers**: also left out
of income and expenses, and not shown as returns. E.g. an expense account that loan or card
payments pass through, from checking to the debt when both sides are recorded. These are
`financing` without a declaration when their names say so: names containing Repayment, or Payment
after Loan, Mortgage or Card, such as `Expenses:CreditCardPayment`, `Expenses:MortgageRepayment`
or `Expenses:Mortgage:Payment` (but not `Expenses:Rent:Payment`). Declare any other:

```beancount
2020-01-01 open Expenses:Transfers:Loan
  cash-flow-role: "financing"
```

The debt's balance already counts the payments, in debt paid down. As spending, a payment recorded
in one year and passed on to the loan in the next would count in the first.

The [Cash Flow](cash-flow.md) report reads the same declarations, moving these accounts from net
income to investing or financing.

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
other assets `investing`, liabilities `financing`, and income and expense accounts `operating`,
except debt-payment accounts (see [transfers](#investment-returns-and-transfers)), which are
`financing`. A declared value that isn't a role (e.g. a
typo) is reported as an error and ignored. The page's "How accounts are classified" section lists
accounts' groups and why: those two levels deep (e.g. `Assets:Bank`), and deeper ones only where
their group differs from their parent's.

Here, roles decide which assets are **cash** (the cash group and the emergency fund), which
liabilities are **debt**, and which income and expense accounts are
[investment returns or transfers](#investment-returns-and-transfers). `cash` is money available now at a fixed value, such as checking
and savings accounts; `investing` is assets whose value moves with markets, such as a brokerage
account. Where money goes doesn't affect savings: money moved into a savings account or a
brokerage account is saved either way, since savings are income minus expenses.
