# Financial Summary

```beancount
2020-01-01 custom "fava-extension" "beancount_sg.ext.summary"
```

A summary of the household's finances for someone who doesn't use Beancount, e.g. a spouse taking
over in case of death: the real-world accounts and what they're worth, the equity in a home or car
with a loan on it, the bills to keep paying, and the accounts that were closed. **Download PDF**
gives the same as a PDF, to print or keep somewhere your family can find it.

![Financial Summary report](images/summary.png)

The summary covers the whole ledger as of today, whatever Fava's filters. Values are at market
value in the first `operating_currency` where there are prices.

## Without Fava

The `bean-summary` command, installed with `beancount-sg` (Fava isn't needed), writes the same PDF
from a ledger file:

```bash
bean-summary ledger.beancount                       # writes financial-summary-<today>.pdf
bean-summary ledger.beancount -o summary.pdf -d 2026-12-31
```

`-o` names the PDF, and `-d` makes the summary as of another date. Errors in the ledger are
reported, but don't stop the summary.

## What it shows

- **Totals:** everything owned (assets), everything owed (loans and credit cards), and net worth.
- **Open accounts:** each open asset and liability account, with the last 4 digits of its number
  and what it's worth (or, for a loan or card, what's owed), in three groups: bank accounts and
  cash, investments and property, and loans and credit cards. Bank accounts are those with the
  `cash` [cash-flow role](cash-flow.md#the-statement): named with Cash, Checking, Savings or Bank,
  or declared `cash`.
- **Loans secured by property:** an asset with a loan opened under the matching account path,
  e.g. `Assets:Home` and `Liabilities:Home:Mortgage`, with its value, what's owed, and the equity:
  the value minus what's owed.
- **Bills:** the accounts you mark, with when each was last paid and how much, the account that
  paid it, and what it came to over the last 12 months.
- **Closed accounts:** with the last 4 digits of their numbers and when they were opened and
  closed, so they're recognized if a statement or letter turns up.

## Setting it up

Give each account its number on its `open` directive. Only the last 4 digits are shown, on the page
and in the PDF:

```beancount
2020-01-01 open Assets:Bank:Checking USD
  account-number: "000123454321"
```

Mark each bill with `bill`, on the account its payments go to: an expense account, e.g. a utility,
or a loan or card. `bill: TRUE` uses the account's name; a string names the bill for the reader:

```beancount
2020-01-01 open Expenses:Home:Electric USD
  bill: "Electric (City Power)"

2020-01-01 open Liabilities:Home:Mortgage USD
  bill: "Mortgage (Hometown Bank)"
```

A bill's payments are the transactions adding to its account: an expense, or a payment on a loan
or card (charges to a card aren't payments). A payment's amount is what left the accounts that paid
it, e.g. the whole mortgage payment from checking, interest included, and those accounts are what
it was paid from.

Download the PDF now and then, as balances and bills change, and keep it with your other important
papers.
