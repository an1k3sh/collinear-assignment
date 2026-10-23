import argparse
import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read(root, name):
    with (root / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def selected(rows, key, cutoff):
    latest = {}
    for row in rows:
        if timestamp(row["recorded_at"]) <= cutoff:
            identity = (row["merchant"], row[key])
            if identity not in latest or int(row["version"]) > int(latest[identity]["version"]):
                latest[identity] = row
    return [row for row in latest.values()
            if row["status"] == "posted" and timestamp(row["effective_at"]) <= cutoff]


def write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reconcile(source, output):
    raw_cutoff = json.loads((source / "cutoff.json").read_text())["cutoff"]
    cutoff = timestamp(raw_cutoff)
    events = selected(read(source, "events.csv"), "event_id", cutoff)
    allocations = selected(read(source, "allocations.csv"), "allocation_id", cutoff)
    bank = [r for r in read(source, "bank.csv") if r["status"] == "posted"
            and timestamp(r["effective_at"]) <= cutoff and timestamp(r["recorded_at"]) <= cutoff]
    settlements = []
    for batch in sorted(read(source, "batches.csv"), key=lambda r: (r["merchant"], r["batch"], r["currency"])):
        matches = lambda r: all(r[k] == batch[k] for k in ("merchant", "batch", "currency"))
        activity = [r for r in events if matches(r)]
        amount = lambda kinds: sum(int(r["amount_cents"]) for r in activity if r["kind"] in kinds)
        sales, refunds, fees, reserves = (amount(kinds) for kinds in (
            {"sale"}, {"refund"}, {"fee"}, {"reserve_hold", "reserve_release"}))
        expected = sales + refunds + fees + reserves
        deposited = sum(int(r["amount_cents"]) for r in bank if matches(r))
        diff = deposited - expected
        status = "matched" if diff == 0 else (
            "pending" if deposited == 0 and date.fromisoformat(batch["due_date"]) > cutoff.date() else "exception")
        settlements.append({k: batch[k] for k in ("merchant", "batch", "currency")} | {
            "sales_cents": sales, "refunds_cents": refunds, "fees_cents": fees,
            "reserve_net_cents": reserves, "expected_cents": expected, "bank_cents": deposited,
            "difference_cents": diff, "status": status})
    aging = []
    for invoice in sorted(read(source, "invoices.csv"), key=lambda r: (r["merchant"], r["invoice_id"])):
        applied = sum(int(r["amount_cents"]) for r in allocations
                      if (r["merchant"], r["invoice_id"]) == (invoice["merchant"], invoice["invoice_id"]))
        face = int(invoice["amount_cents"])
        remaining = face - applied
        due = date.fromisoformat(invoice["accepted"]) + timedelta(days=int(invoice["terms_days"]))
        days = max(0, (cutoff.date() - due).days) if remaining > 0 else 0
        bucket = "closed" if remaining == 0 else "current" if days == 0 else (
            "1-30" if days <= 30 else "31-60" if days <= 60 else "61+")
        aging.append({"merchant": invoice["merchant"], "invoice_id": invoice["invoice_id"],
                      "amount_cents": face, "applied_cents": applied, "open_cents": remaining,
                      "due_date": str(due), "days_overdue": days, "bucket": bucket})
    reserves = []
    for row in sorted(read(source, "opening_reserves.csv"), key=lambda r: (r["merchant"], r["currency"])):
        movement = -sum(int(r["amount_cents"]) for r in events
                        if r["merchant"] == row["merchant"] and r["currency"] == row["currency"]
                        and r["kind"] in ("reserve_hold", "reserve_release"))
        opening = int(row["opening_cents"])
        reserves.append({"merchant": row["merchant"], "currency": row["currency"],
                         "opening_cents": opening, "movement_cents": movement,
                         "closing_cents": opening + movement})
    summary = {"cutoff": raw_cutoff, "reserves": reserves,
               "expected_deposits_cents": sum(r["expected_cents"] for r in settlements),
               "bank_cents": sum(r["bank_cents"] for r in settlements),
               "difference_cents": sum(r["difference_cents"] for r in settlements),
               "open_receivables_cents": sum(r["open_cents"] for r in aging),
               "overdue_receivables_cents": sum(r["open_cents"] for r in aging if r["days_overdue"] > 0)}
    output.mkdir(parents=True, exist_ok=True)
    write(output / "settlements.csv", settlements)
    write(output / "aging.csv", aging)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reconcile(args.input, args.output)
