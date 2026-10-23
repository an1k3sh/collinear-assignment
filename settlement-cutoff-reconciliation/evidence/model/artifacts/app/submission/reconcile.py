#!/usr/bin/env python3
"""April cash and receivables close, rebuilt under POLICY.md.

Usage: python reconcile.py --input DATA_DIR --output OUT_DIR
"""
import argparse
import csv
import io
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

EVENT_SIGNS = {
    "sale": 1,
    "refund": -1,
    "fee": -1,
    "reserve_hold": -1,
    "reserve_release": 1,
}
COMPONENT = {
    "sale": "sales_cents",
    "refund": "refunds_cents",
    "fee": "fees_cents",
    "reserve_hold": "reserve_net_cents",
    "reserve_release": "reserve_net_cents",
}
ALLOCATION_KINDS = {"payment", "credit"}


class CloseError(Exception):
    pass


def parse_ts(value, where):
    v = (value or "").strip()
    if not v.endswith("Z"):
        raise CloseError(f"{where}: timestamp {value!r} must end with Z (UTC)")
    try:
        dt = datetime.fromisoformat(v[:-1] + "+00:00")
    except ValueError as exc:
        raise CloseError(f"{where}: bad timestamp {value!r}: {exc}") from None
    return dt.astimezone(timezone.utc)


def parse_date(value, where):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise CloseError(f"{where}: bad date {value!r}") from None


def parse_int(value, where):
    try:
        return int((value or "").strip())
    except ValueError:
        raise CloseError(f"{where}: expected integer, got {value!r}") from None


def read_csv(path, required):
    if not os.path.isfile(path):
        raise CloseError(f"missing input file: {path}")
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [c for c in required if c not in header]
        if missing:
            raise CloseError(f"{path}: missing columns {missing}")
        rows = []
        for i, row in enumerate(reader, start=2):
            if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
                continue
            row["_where"] = f"{os.path.basename(path)}:{i}"
            rows.append(row)
    return rows


def select_versions(rows, id_field, cutoff, stats):
    """Pick the greatest version recorded at/before cutoff per (merchant, id);
    keep it only if it is posted and effective at/before cutoff."""
    groups = {}
    for r in rows:
        key = (r["merchant"], r[id_field])
        ver = parse_int(r["version"], r["_where"])
        bucket = groups.setdefault(key, {})
        if ver in bucket:
            raise CloseError(f"{r['_where']}: duplicate version {ver} for {key}")
        bucket[ver] = r
    selected = {}
    for key, versions in groups.items():
        known = [
            (v, r) for v, r in versions.items()
            if parse_ts(r["recorded_at"], r["_where"]) <= cutoff
        ]
        if not known:
            stats["not_recorded_by_cutoff"].append(key)
            continue
        ver, row = max(known, key=lambda t: t[0])
        if ver != max(versions):
            stats["later_versions_ignored"].append((key, ver, max(versions)))
        status = row["status"].strip().lower()
        if status != "posted":
            stats["excluded_status"].append((key, ver, status))
            continue
        if parse_ts(row["effective_at"], row["_where"]) > cutoff:
            stats["excluded_future_effective"].append((key, ver))
            continue
        selected[key] = row
    return selected


def new_stats():
    return {
        "not_recorded_by_cutoff": [],
        "later_versions_ignored": [],
        "excluded_status": [],
        "excluded_future_effective": [],
    }


def settle(data_dir, cutoff, notes):
    batches = read_csv(os.path.join(data_dir, "batches.csv"),
                       ["merchant", "batch", "currency", "due_date"])
    events = read_csv(os.path.join(data_dir, "events.csv"),
                      ["merchant", "event_id", "version", "batch", "currency", "kind",
                       "amount_cents", "effective_at", "recorded_at", "status"])
    bank = read_csv(os.path.join(data_dir, "bank.csv"),
                    ["bank_id", "merchant", "batch", "currency", "amount_cents",
                     "effective_at", "recorded_at", "status"])

    rows = {}
    for b in batches:
        key = (b["merchant"], b["batch"], b["currency"])
        if key in rows:
            raise CloseError(f"{b['_where']}: duplicate batch key {key}")
        rows[key] = {
            "merchant": key[0], "batch": key[1], "currency": key[2],
            "sales_cents": 0, "refunds_cents": 0, "fees_cents": 0,
            "reserve_net_cents": 0, "bank_cents": 0,
            "_due": parse_date(b["due_date"], b["_where"]),
        }

    estats = new_stats()
    selected = select_versions(events, "event_id", cutoff, estats)
    out_of_scope_events = []
    sign_normalised = []
    for (merchant, event_id), e in sorted(selected.items()):
        kind = e["kind"].strip()
        if kind not in EVENT_SIGNS:
            raise CloseError(f"{e['_where']}: unknown event kind {kind!r}")
        raw = parse_int(e["amount_cents"], e["_where"])
        amt = EVENT_SIGNS[kind] * abs(raw)
        if amt != raw:
            sign_normalised.append((merchant, event_id, raw, amt))
        key = (merchant, e["batch"], e["currency"])
        if key not in rows:
            out_of_scope_events.append((merchant, event_id, e["batch"], e["currency"]))
            continue
        rows[key][COMPONENT[kind]] += amt

    bank_included, bank_excluded, bank_unmatched = [], [], []
    for d in bank:
        status = d["status"].strip().lower()
        eff = parse_ts(d["effective_at"], d["_where"])
        rec = parse_ts(d["recorded_at"], d["_where"])
        amt = parse_int(d["amount_cents"], d["_where"])
        if status != "posted" or eff > cutoff or rec > cutoff:
            bank_excluded.append((d["bank_id"], d["merchant"], d["batch"], amt,
                                  status, d["effective_at"], d["recorded_at"]))
            continue
        key = (d["merchant"], d["batch"], d["currency"])
        if key not in rows:
            bank_unmatched.append((d["bank_id"], key, amt))
            continue
        rows[key]["bank_cents"] += amt
        bank_included.append((d["bank_id"], key, amt))

    cutoff_date = cutoff.date()
    out = []
    for key in sorted(rows):
        r = rows[key]
        r["expected_cents"] = (r["sales_cents"] + r["refunds_cents"]
                               + r["fees_cents"] + r["reserve_net_cents"])
        r["difference_cents"] = r["bank_cents"] - r["expected_cents"]
        if r["difference_cents"] == 0:
            r["status"] = "matched"
        elif r["bank_cents"] == 0 and r["_due"] > cutoff_date:
            r["status"] = "pending"
        else:
            r["status"] = "exception"
        out.append(r)

    notes["events"] = estats
    notes["events_out_of_scope"] = out_of_scope_events
    notes["event_sign_normalised"] = sign_normalised
    notes["bank_included"] = bank_included
    notes["bank_excluded"] = bank_excluded
    notes["bank_unmatched_key"] = bank_unmatched
    return out


def receivables(data_dir, cutoff, notes):
    invoices = read_csv(os.path.join(data_dir, "invoices.csv"),
                        ["merchant", "invoice_id", "issued", "accepted",
                         "terms_days", "amount_cents"])
    allocs = read_csv(os.path.join(data_dir, "allocations.csv"),
                      ["merchant", "allocation_id", "version", "invoice_id", "kind",
                       "amount_cents", "effective_at", "recorded_at", "status"])
    inv = {}
    for i in invoices:
        key = (i["merchant"], i["invoice_id"])
        if key in inv:
            raise CloseError(f"{i['_where']}: duplicate invoice {key}")
        accepted = parse_date(i["accepted"], i["_where"])
        terms = parse_int(i["terms_days"], i["_where"])
        inv[key] = {
            "merchant": key[0], "invoice_id": key[1],
            "amount_cents": parse_int(i["amount_cents"], i["_where"]),
            "applied_cents": 0,
            "_due": accepted + timedelta(days=terms),
        }

    astats = new_stats()
    selected = select_versions(allocs, "allocation_id", cutoff, astats)
    applied = []
    for (merchant, alloc_id), a in sorted(selected.items()):
        kind = a["kind"].strip().lower()
        if kind not in ALLOCATION_KINDS:
            raise CloseError(f"{a['_where']}: unknown allocation kind {kind!r}")
        key = (merchant, a["invoice_id"])
        if key not in inv:
            raise CloseError(f"{a['_where']}: allocation {alloc_id} references "
                             f"unknown invoice {key}")
        amt = parse_int(a["amount_cents"], a["_where"])
        if amt < 0:
            raise CloseError(f"{a['_where']}: allocation amount must be positive")
        inv[key]["applied_cents"] += amt
        applied.append((merchant, alloc_id, a["version"], a["invoice_id"], kind, amt))

    cutoff_date = cutoff.date()
    out = []
    for key in sorted(inv):
        r = inv[key]
        r["open_cents"] = r["amount_cents"] - r["applied_cents"]
        if r["open_cents"] < 0:
            notes.setdefault("overpaid", []).append(key)
        days = max(0, (cutoff_date - r["_due"]).days) if r["open_cents"] > 0 else 0
        r["due_date"] = r["_due"].isoformat()
        r["days_overdue"] = days
        if r["open_cents"] == 0:
            r["bucket"] = "closed"
        elif days == 0:
            r["bucket"] = "current"
        elif days <= 30:
            r["bucket"] = "1-30"
        elif days <= 60:
            r["bucket"] = "31-60"
        else:
            r["bucket"] = "61+"
        out.append(r)

    notes["allocations"] = astats
    notes["allocations_applied"] = applied
    return out


def reserves(data_dir, settlements):
    opening = read_csv(os.path.join(data_dir, "opening_reserves.csv"),
                       ["merchant", "currency", "opening_cents"])
    res = {}
    for o in opening:
        key = (o["merchant"], o["currency"])
        if key in res:
            raise CloseError(f"{o['_where']}: duplicate opening reserve {key}")
        res[key] = {"opening": parse_int(o["opening_cents"], o["_where"]), "movement": 0}
    for s in settlements:
        if s["reserve_net_cents"] == 0 and (s["merchant"], s["currency"]) not in res:
            continue
        key = (s["merchant"], s["currency"])
        entry = res.setdefault(key, {"opening": 0, "movement": 0})
        entry["movement"] += -s["reserve_net_cents"]
    return [
        {"merchant": m, "currency": c, "opening_cents": v["opening"],
         "movement_cents": v["movement"], "closing_cents": v["opening"] + v["movement"]}
        for (m, c), v in sorted(res.items())
    ]


SETTLEMENT_COLS = ["merchant", "batch", "currency", "sales_cents", "refunds_cents",
                   "fees_cents", "reserve_net_cents", "expected_cents", "bank_cents",
                   "difference_cents", "status"]
AGING_COLS = ["merchant", "invoice_id", "amount_cents", "applied_cents", "open_cents",
              "due_date", "days_overdue", "bucket"]


def csv_text(rows, cols):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def write_atomic(path, text):
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=os.path.basename(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def check(cond, msg):
    if not cond:
        raise CloseError(f"self-check failed: {msg}")


def run(input_dir, output_dir):
    if not os.path.isdir(input_dir):
        raise CloseError(f"input directory not found: {input_dir}")
    cutoff_path = os.path.join(input_dir, "cutoff.json")
    if not os.path.isfile(cutoff_path):
        raise CloseError(f"missing input file: {cutoff_path}")
    with open(cutoff_path, encoding="utf-8-sig") as fh:
        try:
            cutoff_raw = json.load(fh)["cutoff"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CloseError(f"{cutoff_path}: cannot read 'cutoff': {exc}") from None
    cutoff = parse_ts(cutoff_raw, "cutoff.json")

    notes = {}
    settlements = settle(input_dir, cutoff, notes)
    aging = receivables(input_dir, cutoff, notes)
    reserve_rows = reserves(input_dir, settlements)

    # Never sum across currencies: headline totals are USD; others broken out.
    by_ccy = {}
    for s in settlements:
        t = by_ccy.setdefault(s["currency"], {"expected_deposits_cents": 0,
                                              "bank_cents": 0, "difference_cents": 0})
        t["expected_deposits_cents"] += s["expected_cents"]
        t["bank_cents"] += s["bank_cents"]
        t["difference_cents"] += s["difference_cents"]
    if len(by_ccy) > 1 or (by_ccy and "USD" not in by_ccy):
        print(f"warning: settlement currencies {sorted(by_ccy)}; headline deposit "
              f"totals are USD only, see deposits_by_currency", file=sys.stderr)
    head = by_ccy.get("USD", {"expected_deposits_cents": 0, "bank_cents": 0,
                              "difference_cents": 0})

    summary = {
        "cutoff": cutoff_raw,
        "expected_deposits_cents": head["expected_deposits_cents"],
        "bank_cents": head["bank_cents"],
        "difference_cents": head["difference_cents"],
        "open_receivables_cents": sum(a["open_cents"] for a in aging),
        "overdue_receivables_cents": sum(a["open_cents"] for a in aging
                                         if a["days_overdue"] > 0),
        "reserves": reserve_rows,
    }
    if len(by_ccy) > 1 or (by_ccy and "USD" not in by_ccy):
        summary["deposits_by_currency"] = by_ccy

    for s in settlements:
        check(s["expected_cents"] == s["sales_cents"] + s["refunds_cents"]
              + s["fees_cents"] + s["reserve_net_cents"], f"expected {s['batch']}")
        check(s["difference_cents"] == s["bank_cents"] - s["expected_cents"],
              f"difference {s['batch']}")
        check(s["sales_cents"] >= 0 and s["refunds_cents"] <= 0 and s["fees_cents"] <= 0,
              f"component signs {s['merchant']}/{s['batch']}")
    for r in reserve_rows:
        check(r["closing_cents"] == r["opening_cents"] + r["movement_cents"],
              f"reserve roll-forward {r['merchant']}")
    for a in aging:
        check(a["open_cents"] == a["amount_cents"] - a["applied_cents"],
              f"open balance {a['invoice_id']}")

    os.makedirs(output_dir, exist_ok=True)
    write_atomic(os.path.join(output_dir, "settlements.csv"),
                 csv_text(settlements, SETTLEMENT_COLS))
    write_atomic(os.path.join(output_dir, "aging.csv"), csv_text(aging, AGING_COLS))
    write_atomic(os.path.join(output_dir, "summary.json"),
                 json.dumps(summary, indent=2) + "\n")

    print(f"cutoff {cutoff_raw}: {len(settlements)} settlement rows, "
          f"{len(aging)} invoices; expected {summary['expected_deposits_cents']} "
          f"bank {summary['bank_cents']} diff {summary['difference_cents']}; "
          f"open AR {summary['open_receivables_cents']} "
          f"overdue {summary['overdue_receivables_cents']}")
    for s in settlements:
        if s["status"] != "matched":
            print(f"  {s['status']}: {s['merchant']}/{s['batch']}/{s['currency']} "
                  f"expected {s['expected_cents']} bank {s['bank_cents']} "
                  f"diff {s['difference_cents']}")
    for label in ("events", "allocations"):
        for k, v in notes[label].items():
            for item in v:
                print(f"  {label} {k}: {item}")
    for k in ("events_out_of_scope", "event_sign_normalised", "bank_excluded",
              "bank_unmatched_key", "overpaid"):
        for item in notes.get(k, []):
            print(f"  {k}: {item}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    try:
        return run(args.input, args.output)
    except (CloseError, OSError, csv.Error) as exc:
        print(f"reconcile: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
