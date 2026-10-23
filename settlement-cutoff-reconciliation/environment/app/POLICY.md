# Close policy

Read cutoff.json for an inclusive UTC timestamp. This is an "as known at cutoff"
close: BOTH effective_at and recorded_at must be <= cutoff to include a posting.
All timestamps end Z. All amounts are integer cents in USD; never sum currencies.
IDs are exact text, including leading zeros; merchant is part of every join key.

Events and allocations are versioned independently by (merchant,event_id) or
(merchant,allocation_id). Select the greatest integer version whose recorded_at
is <= cutoff FIRST, then apply its effective date and status. If the selected
version is cancelled/draft or future-effective, exclude the whole logical item;
do not fall back to an older version. Versions are unique and valid.

## Settlements

batches.csv lists the batches in scope, their currency and due_date. Emit one row
per (merchant,batch,currency), sorted lexicographically. Column order is flexible.
events.csv kinds and signs:
sale positive, refund negative, fee negative, reserve_hold negative,
reserve_release positive. Latest posted revisions alone count.

Output columns: merchant,batch,currency,sales_cents,refunds_cents,fees_cents,
reserve_net_cents,expected_cents,bank_cents,difference_cents,status.
expected is the sum of the four component amounts. Reserve net is the signed
hold/release contribution to the deposit. Bank records are selected with the
same two-date cutoff, posted status, and explicit merchant/batch/currency keys.
Do not match by amount; sum multiple bank lines for a key. Difference = bank -
expected. Status: matched if difference zero; pending if nonzero, bank zero and
due_date is after cutoff's UTC date; otherwise exception.

opening_reserves.csv plus holds minus releases yields closing reserves by
merchant/currency. A hold's event amount is negative, so reserve movement is
the NEGATIVE of the settlement reserve_net. No reserve movement is a fee.

## Receivables

invoices.csv contains issued date, accepted date, terms_days, amount_cents.
Every invoice is in scope. Due date = accepted date + terms_days calendar days,
not issued date. allocations.csv gives payment or credit postings linked to
merchant/invoice_id, never infer allocations from bank deposits.
Allocation amount is positive and reduces the balance. Apply the same version,
status and two-date cutoff rules. Never apply draft credits.

aging.csv columns: merchant,invoice_id,amount_cents,applied_cents,open_cents,
due_date,days_overdue,bucket. open = amount - applied; supplied cases do not
overpay. days_overdue = max(0, cutoff_date - due_date) for positive open balances,
otherwise zero. bucket is closed if open zero; current if days_overdue zero;
1-30 if 1..30; 31-60 if 31..60; 61+ otherwise. Sort merchant/invoice_id.

summary.json:
{
 "cutoff": "the input timestamp",
 "expected_deposits_cents": integer,
 "bank_cents": integer,
 "difference_cents": integer,
 "open_receivables_cents": integer,
 "overdue_receivables_cents": integer,
 "reserves":[{"merchant":string,"currency":"USD","opening_cents":integer,
              "movement_cents":integer,"closing_cents":integer}]
}
Reserves sorted merchant/currency. The input universe is internally linked and
valid; the task is correct reconciliation, not unspecified malformed-input handling.
Reruns must replace outputs, not append duplicates. Failures must exit nonzero
with a diagnostic; no blank-success reports.
