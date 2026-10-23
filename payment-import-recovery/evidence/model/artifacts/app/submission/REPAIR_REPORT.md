# Payment import repair report

## Incident summary

`incidents/import.log` shows `north/P-001` committed but the response was lost
(connection reset), after which `data/payments.csv` was retried. The importer
printed success, yet the INV-9 allocation was missing and no worker traceback
was collected. The operator also noted that P-001 and P-002 share a time and
amount but pay different invoices.

## Defects found in `import_payments.py`

| # | Defect | Contract impact |
|---|--------|-----------------|
| 1 | Retry/dedup lookup matched on `paid_at` + `cents` across **all** tenants/keys | P-002 (and south/P-001) were treated as retries of north/P-001 and silently dropped. The key must be `(tenant,payment_id)`. |
| 2 | No fingerprint comparison | Reusing a key with different data returned the old receipt instead of an explicit error. |
| 3 | `cents = int(float(amount) * 100)` | Binary float truncation: `0.29` → 28 cents (P-004). |
| 4 | All-digit invoice IDs normalized with `str(int(...))` | `"00123"` became `"123"`, so payments landed on the wrong invoice. |
| 5 | Payment committed, then `after_commit()`, then receipt in a second commit | Not atomic; a hook failure (the logged connection reset) left a payment with no receipt. Hook ran before the receipt was stored. |
| 6 | CLI discarded the `submit()` futures and built the report from the **input** | Worker exceptions vanished; report/exit code were optimistic (always "ok", exit 0) regardless of what was stored. That is how the missing INV-9 allocation was reported as success. |
| 7 | Line numbers from `enumerate`, not the CSV reader | Wrong lines with blank lines/multi-line quoted fields. |
| 8 | Weak timestamp check (`fromisoformat` accepts date-only, etc.); malformed file raised a traceback; missing DB path silently created an empty database | Contract validation and diagnostics. |
| 9 | Duplicate keys inside one file processed concurrently | Which conflicting row "won" was nondeterministic. |

## Repairs

* `normalized()`: strict ASCII amount regex, exact integer cents
  (`dollars*100 + pennies`), range 1..2^63-1; strict `YYYY-MM-DDTHH:MM[:SS[.ffffff]]Z`
  timestamps validated as real dates; IDs kept as exact, case-sensitive strings.
* `apply_payment()`: opens the DB in `mode=rw` (never creates it), with a 30 s
  busy timeout and `BEGIN IMMEDIATE` **before** any read, so racing processes
  serialize on the write lock. Looks up the receipt by `(tenant,payment_id)`:
  same fingerprint → returns the stored original receipt (no hook); different
  fingerprint → `PaymentConflict`. Unknown invoice → `UnknownInvoice`. Payment
  and receipt are inserted in **one** transaction; the hook runs only after
  that commit and its exception propagates (a retry then returns the stored
  receipt). Any failure rolls back, so failed rows consume no IDs. A payment
  left without a receipt by the old importer is adopted only if identical,
  otherwise reported as a conflict; existing rows are never updated.
  The fingerprint format is unchanged (sha256 of the sorted-key JSON of the
  normalized row), so the existing P-001 receipt matches.
  Error classes subclass `ValueError` for compatibility.
* `run()`: reads/validates the whole file first (header set, BOM, NUL bytes,
  bad quoting, encoding, missing file → exit 2 with a stderr diagnostic, no
  DB changes, no report). Checks the DB exists with the expected tables. Rows
  are grouped by key: rows with the same key run sequentially in input order
  (first valid row wins), distinct keys run concurrently. Every future's
  result is collected; validation/conflict errors, transient SQLite errors
  (retried idempotently first) and unexpected exceptions (traceback printed to
  stderr) all become explicit error rows. Report rows are sorted by physical
  line, counts derive from actual outcomes, exit 1 if any error. The report is
  written to a temp file in the target directory, fsynced, and `os.replace`d;
  parent folders are created.

## Data recovery

* Backed up the original DB before any change. It contained only the valid,
  committed north/P-001 payment and receipt; both were preserved byte-for-byte.
* Ran `python import_payments.py --db state/payments.sqlite --input data/payments.csv --report submission/import-report.json`
  → exit 0, 7 rows ok, 0 errors (line 5 is the exact retry of P-001).
* `state/payments.sqlite` now holds exactly the 6 unique export payments, each
  with one receipt: north P-001 (00123, 2500), P-002 (123, 2500),
  P-003 (INV-9, 1999), P-004 (00123, 29), P-005 (INV-9, 10001), south P-001
  (00123, 2500). Invoices unchanged; `PRAGMA integrity_check` = ok. A second
  run is a no-op with an identical report.

## Tests

`python -m unittest discover -s tests` — 27 tests in `tests/test_import_payments.py`
(each builds a fresh DB via `tools/seed.py` in a temp dir) covering exact
cents, invalid amounts/timestamps, leading-zero invoice IDs, same time/amount
not being a duplicate, tenant scoping, exact retry vs conflicting reuse,
failed rows consuming no IDs, hook ordering/failure/recovery, busy-lock
waiting, an 8-process race on one key, report order/line numbers/error rows,
duplicate keys within a file, malformed files, missing DB, atomic report
writing, surfaced worker exceptions, and concurrent CLI runs after a partial
import. 23 of them fail against the original importer.
