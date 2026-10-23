"""Independent decimal/account-scope treasury reconciliation."""

from collections import Counter
from decimal import Decimal
import csv


def reconciliation(directory):
    with (directory / "cashbook.csv").open() as stream:
        ledger = {r["bank_id"]: r for r in csv.DictReader(stream)}
    with (directory / "bank_export.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    counts = Counter(r["bank_id"] for r in rows)
    unique = {row["bank_id"]: row for row in rows}
    items = []
    cash, debt = Decimal(0), Decimal(0)
    for bank_id, row in sorted(unique.items()):
        item = {"bank_id": bank_id}
        if row["account"] != "MAIN":
            reason = "other_account"
        elif row["currency"] != "USD":
            reason = "other_currency"
        elif row["status"] != "settled":
            reason = "not_settled"
        elif row["posted_date"] > "2025-12-31":
            reason = "after_cutoff"
        else:
            reason = None
        if reason:
            item.update(classification="excluded", reason=reason)
        elif bank_id in ledger:
            assert Decimal(ledger[bank_id]["cash_amount"]) == Decimal(row["amount"])
            item.update(classification="matched", book_id=ledger[bank_id]["book_id"])
        else:
            adjustment = Decimal(row["amount"])
            revolver = adjustment if row["category"] == "revolver" else Decimal(0)
            item.update(classification="adjustment", cash_adjustment=float(adjustment),
                        debt_adjustment=float(revolver))
            cash += adjustment
            debt += revolver
        items.append(item)
    return {
        "cutoff": "2025-12-31", "account": "MAIN", "currency": "USD",
        "items": items, "duplicate_bank_ids": sorted(k for k, n in counts.items() if n > 1),
        "net_cash_adjustment": float(cash), "net_debt_adjustment": float(debt),
        "corrected_opening_cash": float(30000 + cash),
        "corrected_opening_revolver": float(30000 + debt),
    }
