# April close – repair report

Command: `python submission/reconcile.py --input data --output submission/close`
Cutoff: `2026-04-30T23:59:59Z` (inclusive). A posting counts only if both `effective_at` and `recorded_at` are ≤ cutoff. For each `(merchant, id)`, the script selects the highest version recorded by cutoff first. If that version is not `posted`, or is effective after cutoff, the whole item is excluded.

## Reconstructed close

| merchant | batch | sales | refunds | fees | reserve net | expected | bank | diff | status |
|---|---|---|---|---|---|---|---|---|---|
| north | B-17 | 18000 | -2000 | -450 | -1000 | 14550 | 14550 | 0 | matched |
| north | B-18 | 5000 | 0 | -175 | +400 | 5225 | 5000 | **-225** | **exception** |
| north | B-19 | 7000 | 0 | -210 | 0 | 6790 | 0 | -6790 | pending |
| south | B-17 | 10000 | 0 | -300 | 0 | 9700 | 9700 | 0 | matched |

Totals (USD): expected 36265, bank 29250, difference **-7015**. This is the B-18 exception (-225) plus B-19, which is pending and not yet due (-6790).

Reserves: north 1000 + 1000 hold − 400 release = **1600**; south 500 → **500**. No reserve movement is booked as a fee.

| merchant | invoice | amount | applied | open | due | days | bucket |
|---|---|---|---|---|---|---|---|
| north | 00123 | 10000 | 2500 | 7500 | 2026-05-20 | 0 | current |
| north | 123 | 20000 | 8000 | 12000 | 2026-03-31 | 30 | 1-30 |
| north | PAID-9 | 5000 | 5000 | 0 | 2026-02-17 | 0 | closed |
| south | 00123 | 15000 | 5000 | 10000 | 2026-05-01 | 0 | current |

Open receivables are 29500, of which 12000 is overdue.

## Draft-close discrepancies

1. **all_deposits 29250, "bank agrees" / all_batches "balanced by taking deposited amount as expected".** The draft set expected equal to the bank amount, which hides any difference by construction. Expected is the net of the events: 36265. The bank shows 29250, so the difference is -7015 and cannot be plugged.
2. **B-17 combined across merchants.** Merchant is part of the key. north/B-17 (14550 vs DEP-1) and south/B-17 (9700 vs DEP-2) are separate rows, and each matches on its own key, not by amount.
3. **north_B18 5000, "gross sale matched deposit".** DEP-3 (5000) equals sale S3 only by coincidence. The net settlement is 5000 − 175 fee (F2 v2, the latest version recorded by cutoff) + 400 reserve release (L1) = 5225. X1 is excluded because its latest version recorded by cutoff (v2, 19:00) is cancelled. The deposit is **short by 225**. This is an unresolved **exception** that needs follow-up with the processor or bank. It must not be absorbed into fees.
4. **north_invoice_00123 5500, "2000 credit applied".** C1 is a *draft* credit and is never applied. Only payment A1 (2500) applies, so the open balance is **7500**. Invoice `00123` is also a different invoice from `123`, and from south's `00123`. IDs are exact text and joins include the merchant.
5. **north_invoice_00123_days_overdue 30, "aged from issue".** The due date is acceptance (2026-04-20) + 30 days = 2026-05-20. The invoice is therefore **current, with 0 days overdue**. Aging from the issue date (2026-03-01) was wrong.

## Cutoff exclusions (May 1 export)

- Event `north/F2` v3 (-200), recorded 2026-05-01: ignored. v2 (-175), recorded 2026-04-30 18:00, is used.
- Event `north/LATE` refund (-500), recorded 2026-05-01: excluded.
- Allocation `north/LATE` payment (1000) on invoice 123, recorded 2026-05-01: excluded.
- Allocation `north/C2`: v2 (3000), recorded 2026-04-21, supersedes v1 (2000).
- Bank `DEP-4` (6790) for north/B-19 is effective and recorded 2026-05-02, so bank = 0. B-19 is due 2026-05-02, after the cutoff date, so it is **pending**, not an exception.

## Unresolved

- **north/B-18: -225 exception.** The bank deposit is 225 below the net settlement. The late fee revision to -200 and the late -500 refund are not knowable at cutoff, and neither explains the gap exactly (fee v3 would give -200, plus refund -700). Keep it open for investigation.
- north/B-19: -6790 pending. A deposit is expected after cutoff.

## Checks performed by the script

- Highest version recorded by cutoff is selected first; cancelled, draft, or future-effective selections drop the whole item, with no fallback to older versions.
- Bank lines are filtered on status, effective date and recorded date, then summed per merchant/batch/currency. There is no amount matching.
- `expected = sum of components`, `difference = bank − expected`, `closing = opening + movement`, `open = amount − applied` are asserted before any output is written.
- Event signs are normalised by kind, and reserve movement is the negation of reserve net.
- Allocations to unknown invoices, unknown kinds, duplicate versions or keys, bad timestamps and missing files all exit with code 1 and a diagnostic.
- Outputs are written atomically and replaced on rerun. A rerun produces byte-identical outputs.
- Headline deposit totals are never summed across currencies. Non-USD data is reported in `deposits_by_currency`.
