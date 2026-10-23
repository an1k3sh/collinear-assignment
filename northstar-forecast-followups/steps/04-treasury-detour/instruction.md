# Task switch: reconcile the treasury cutover; do not edit the forecasts yet

Pause model changes. Work on the finance cutover review using the newly
delivered `/app/treasury/bank_export.csv` and `cashbook.csv`.
Produce `/app/output/treasury_reconciliation.json`. Keep the two forecast
workbooks, handoff and board pack exactly as you left them in financial state;
this detour does not authorize model or source changes.

Scope is USD account MAIN through **2025-12-31**. Bank amount signs are signed
cash movements. Each distinct bank transaction ID counts once. A repeated
export row with the same bank ID is a duplicate delivery, not a second cash
movement; list its ID once in `duplicate_bank_ids`.

Classify each unique bank ID, following this precedence:

1. If account is not MAIN, reason `other_account`.
2. If currency is not USD, reason `other_currency`.
3. If status is not `settled`, reason `not_settled`.
4. If posted_date is after 2025-12-31, reason `after_cutoff`.
5. Otherwise find a cashbook row whose `bank_id` matches. If present, classify
   `matched`, including its `book_id`. Its cash amount must match exactly.
6. Otherwise classify `adjustment`. Include its signed `cash_adjustment` and
   `debt_adjustment`. The cash adjustment equals the signed bank amount.
   For category `revolver`, the debt adjustment equals the signed cash amount
   (draw positive, repayment negative); all other categories have zero debt.

Reversals are separately settled transactions and should be classified
individually, even if their net adjustment is zero. Do not cancel a legitimate
same-amount transaction just because another has the same amount.

Output schema (one object per unique ID, in any order):

```json
{
  "cutoff": "2025-12-31", "account": "MAIN", "currency": "USD",
  "items": [
    {"bank_id": "example", "classification": "matched", "book_id": "example"},
    {"bank_id": "example2", "classification": "excluded", "reason": "not_settled"},
    {"bank_id": "example3", "classification": "adjustment",
     "cash_adjustment": 0, "debt_adjustment": 0}
  ],
  "duplicate_bank_ids": [],
  "net_cash_adjustment": 0, "net_debt_adjustment": 0,
  "corrected_opening_cash": 0, "corrected_opening_revolver": 0
}
```

Corrected opening balances are the original Historical!D22 cash of 30,000 and
D23 revolver of 30,000 plus their respective net adjustments. Do not insert
them into either workbook until separately authorized. Exact ID membership and
classifications matter; numeric amounts use the same 0.005 tolerance.
