# Import contract

CLI: `python import_payments.py --db PATH --input CSV --report JSON`.
Input columns: tenant,payment_id,invoice_id,paid_at,amount. IDs are nonempty
case-sensitive strings; `"00123"` and `"123"` are different invoice IDs.
paid_at is an ISO-8601 UTC timestamp ending Z. amount is a positive decimal
dollar string with exactly two fractional digits; use integer cents.

SQLite tables:
* invoices(tenant,invoice_id,due_cents), primary key (tenant,invoice_id).
* payments(tenant,payment_id,invoice_id,paid_at,cents), primary key (tenant,payment_id).
* receipts(tenant,payment_id,fingerprint,response), same primary key.

Deduplicate by (tenant,payment_id), NOT amount/date or invoice. Fingerprint the
complete semantic row, normalizing amount to cents. An exact retry returns the
original receipt; reuse for a different row is an explicit error. A receipt is
`{tenant,payment_id,invoice_id,cents}`. No overpayment restrictions are requested.
An unknown invoice, invalid amount/timestamp or conflicting key is an error;
never silently skip it. Failed rows consume no IDs. Each row is its own atomic
transaction: payment and receipt commit together. Existing rows are immutable.

`apply_payment(db_path,row,after_commit=None)` returns the receipt. The optional
zero-argument hook runs AFTER a successful NEW commit (not on retry). If it
throws, propagate the error: the write committed and a retry must recover it.
Independent processes may race the same key; exactly one payment/receipt pair
must exist. Use a busy timeout and correct transaction ordering.

CLI processes all rows, preserving input row order in its report even when
working concurrently. Output:
`{"rows":[{"line":2,"status":"ok","receipt":{...}}, ...],"ok":N,"errors":M}`.
An error row has `line,status:"error",error:nonempty explanatory string` and no
receipt. Return exit code 1 if any row failed, otherwise 0. A retry can be
reported as ok; do not promise whether it was newly applied.
Header is line 1. Malformed whole files must return nonzero with a diagnostic.
Write reports atomically via temporary file and rename; create parent folders.
Do not make workers' exceptions disappear. Re-running after any partial success
must be safe. Reports must reflect actual stored outcomes, not optimistic counts.

The delivered database must contain exactly the unique payments in the supplied
export. Existing invoice definitions must not change. The supplied incident
database contains one committed payment and receipt, not corrupt history.
