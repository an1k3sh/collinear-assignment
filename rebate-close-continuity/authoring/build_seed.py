"""Create original synthetic ERP exports; no public benchmark records are used."""
import json
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill

ROOT = Path(__file__).resolve().parents[1]
HEADERS = ["event_id", "revision", "recorded_at", "kind", "line_id", "return_of",
           "vendor", "occurred_on", "qty", "unit", "price", "status"]
GROUPS = ["Aster", "Birch", "Cedar", "Delta"]
CUTOFFS = ["2026-03-31", "2026-04-15", "2026-06-30"]


def event(eid, date, line="", vendor="", qty=1, unit="EA", price=1,
          kind="BUY", ref="", rev=1, recorded=None, status="ACTIVE"):
    return [eid, rev, recorded or date, kind, line, ref, vendor, date,
            qty, unit, price if kind == "BUY" else None, status]


def generate():
    rng = random.Random(472019)
    events = []
    lines = []
    for i in range(1, 145):
        date = (datetime(2026, 1, 2) + timedelta(days=(i * 17) % 178)).date().isoformat()
        sku = f"SKU-{i % 6 + 1}"
        line = f"INV-{i:04d}"
        lines.append([line, sku])
        events.append(event(f"P{i:04d}", date, line, f"V{i % 8 + 1}",
                            qty=rng.randint(3, 28), unit="PACK" if i % 3 else "EA",
                            price=rng.choice([19.99, 12.345, 43.21, 99.95, 7.005, 158.75])))
        if i % 4 == 0:
            ret_date = (datetime.fromisoformat(date) + timedelta(days=9 + i % 30)).date().isoformat()
            events.append(event(f"R{i:04d}", ret_date, qty=1 + i % 3,
                                unit="EA", kind="RETURN", ref=line))

    # Isolated keys make a vanished prior key and an exact tier edge observable.
    lines.extend([["BOUNDARY", "SKU-1"], ["FRACTION", "SKU-2"], ["MOVED", "SKU-3"],
                  ["CANCEL", "SKU-1"], ["REOPEN", "SKU-1"], ["DATE-EDGE", "SKU-1"]])
    events.extend([
        event("EDGE", "2026-03-30", "BOUNDARY", "VX", 1, "EA", 1000),
        event("FRACTION-BUY", "2026-03-02", "FRACTION", "V2", 2, "PACK", 19.99),
        event("FRACTION-RETURN", "2026-03-03", kind="RETURN", ref="FRACTION", qty=1),
        event("MOVING", "2026-03-18", "MOVED", "VM", 10, "EA", 130),
        event("CANCELLED", "2026-03-11", "CANCEL", "V1", 4, "EA", 75.55),
        event("REOPENED", "2026-03-12", "REOPEN", "V3", 6, "EA", 27.5),
        event("ALIAS-EDGE", "2026-04-01", "DATE-EDGE", "V1", 2, "EA", 411),
    ])
    late = [
        event("MOVING", "2026-03-18", "MOVED", "V2", 8, "EA", 130,
              rev=2, recorded="2026-04-04"),
        event("MOVING-RETURN", "2026-04-10", kind="RETURN", ref="MOVED", qty=2),
        event("CANCELLED", "2026-03-11", "CANCEL", "V1", 4, "EA", 75.55,
              rev=2, recorded="2026-04-02", status="VOID"),
        event("REOPENED", "2026-03-12", "REOPEN", "V3", 6, "EA", 27.5,
              rev=2, recorded="2026-04-03", status="VOID"),
        event("REOPENED", "2026-03-12", "REOPEN", "V3", 7, "EA", 27.5,
              rev=3, recorded="2026-04-12"),
        event("FRACTION-APRIL", "2026-04-11", kind="RETURN", ref="FRACTION", qty=1),
        event("EARLY-CREDIT", "2026-04-08", kind="RETURN", ref="INV-0012", qty=1),
    ]
    # An older revision arriving at the end of a physical export must not win.
    late.append(event("MOVING", "2026-03-18", "MOVED", "VM", 10, "EA", 130,
                      recorded="2026-03-18"))
    final = [
        event("EDGE-REFUND", "2026-05-01", kind="RETURN", ref="BOUNDARY",
              qty=0.001, unit="EA"),
        event("FRACTION-JUNE", "2026-06-03", kind="RETURN", ref="FRACTION", qty=2),
        event("MOVING", "2026-03-18", "MOVED", "V2", 9, "EA", 145.005,
              rev=3, recorded="2026-06-05"),
        event("MOVING-JUNE", "2026-06-07", kind="RETURN", ref="MOVED", qty=1),
    ]
    products = [[f"SKU-{i}", [1, 12, 6, 24, 10, 5][i - 1], i != 6]
                for i in range(1, 7)]
    aliases = []
    for i in range(1, 9):
        aliases.extend([[f"V{i}", "2026-01-01", "2026-04-01", GROUPS[(i - 1) % 4]],
                        [f"V{i}", "2026-04-01", None, GROUPS[i % 4]]])
    aliases.extend([["VX", "2026-01-01", None, "Exact"],
                    ["VM", "2026-01-01", None, "Legacy"]])
    contracts = []
    for group in GROUPS + ["Exact", "Legacy"]:
        for quarter in ["2026-Q1", "2026-Q2"]:
            for threshold, rate in [(0, 125), (100000, 250), (350000, 475), (800000, 600)]:
                contracts.append([group, quarter, threshold, rate + (25 if quarter.endswith("Q2") else 0)])

    for phase, cutoff in enumerate(CUTOFFS, 1):
        wb = Workbook()
        del wb[wb.sheetnames[0]]
        ws = wb.create_sheet("Events")
        ws.append(HEADERS)
        export = [r for r in events if r[2] <= cutoff]
        if phase >= 2:
            export += late
        if phase >= 3:
            export += final
        rng.shuffle(export)
        # This duplicate is deliberately physically last, not the latest version.
        if phase >= 2:
            export.append(late[-1])
        # Identical duplicate revisions are legal replayed records.
        for row in export:
            ws.append(row)
        for title, headers, values in [
            ("Lines", ["line_id", "sku"], lines),
            ("Products", ["sku", "units_per_pack", "eligible"], products),
            ("Aliases", ["vendor", "valid_from", "valid_until", "group"], aliases),
            ("Contracts", ["group", "quarter", "threshold_cents", "rate_bps"], contracts),
        ]:
            sheet = wb.create_sheet(title)
            sheet.append(headers)
            for row in values:
                sheet.append(row)
        notes = wb.create_sheet("OperatorNotes")
        notes.append(["Supplier rebate review notebook"])
        notes.merge_cells("A1:D1")
        notes.append([])
        notes.append(["owner", "reviewed", "note", "severity"])
        notes.append(["M. Ortiz", "2026-03-28", "Do not net April credits into Q2 by arrival date.", "high"])
        notes.append(["L. Chen", "2026-03-29", "Preserve approved closes during reorganization.", "high"])
        notes["C4"].comment = Comment("Finance reviewed: use original invoice identity.", "M. Ortiz")
        notes["B4"].fill = PatternFill("solid", fgColor="FFFFC000")
        notes["D5"].fill = PatternFill("solid", fgColor="FFFF8080")
        notes.freeze_panes = "C4"
        wb.properties.created = wb.properties.modified = datetime(2026, 3, 1)
        fixtures = ROOT / "tests" / "fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        fixture = fixtures / f"source-{phase}.xlsx"
        wb.save(fixture)
        target = (ROOT / "environment" / "seed" if phase == 1 else
                  ROOT / "steps" / ["01-provisional", "02-restatement", "03-roll-forward"][phase - 1] / "workdir")
        (target / "inputs").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, target / "inputs" / "source.xlsx")
        (target / "inputs" / "turn.json").write_text(json.dumps({"phase": phase, "as_of": cutoff}) + "\n")
    shutil.copyfile(ROOT / "instruction.md", ROOT / "environment" / "seed" / "docs" / "task-overview.md")
    extend_claim_horizon()
    print("Created three synthetic source exports and their immutable grading fixtures.")


def extend_claim_horizon():
    fixtures = ROOT / "tests" / "fixtures"
    rng = random.Random(283716)
    groups = GROUPS + ["Exact"]
    claims = []
    for g, group in enumerate(groups):
        for i in range(1, 10):
            amount = rng.randint(120, 1100) if group == "Exact" else rng.randint(2200, 36000)
            if group != "Exact" and i <= 3:
                amount = [62000, 47000, 37000][i - 1] + 137 * g
            quarter = "2026-Q1" if group == "Exact" or i % 2 else "2026-Q2"
            family = f"choice-{1 if i in (1, 2) else 5 if i in (5, 6) else i}"
            prerequisite = f"{group}-01" if i == 4 else f"{group}-05" if i == 8 else None
            claims.append([f"{group}-{i:02d}", 1, "2026-06-20", group, quarter, amount,
                           (i - 1) // 3 + 1, rng.randint(3, 21),
                           "WIRE" if (g + i) % 2 else "PORTAL", family, prerequisite, "OPEN"])
    for phase, name, cutoff in [(4, "04-claim-batch", "2026-06-30"),
                                 (5, "05-remittance-replan", "2026-07-15")]:
        work = ROOT / "steps" / name / "workdir" / "inputs"
        work.mkdir(parents=True, exist_ok=True)
        financial = load_workbook(fixtures / "source-3.xlsx")
        if phase == 5:
            financial["Events"].append(event("FRACTION-JULY", "2026-07-04", kind="RETURN",
                                             ref="FRACTION", qty=0.5))
            financial["Events"].append(event("MOVING", "2026-03-18", "MOVED", "V2", 8, "EA", 119.995,
                                             rev=4, recorded="2026-07-03"))
            financial["Events"].append(event("P0001", "2026-01-19", "INV-0001", "V2", 1, "PACK", 1,
                                             rev=2, recorded="2026-07-01", status="VOID"))
        financial.save(fixtures / f"source-{phase}.xlsx")
        shutil.copyfile(fixtures / f"source-{phase}.xlsx", work / "source.xlsx")
        (work / "turn.json").write_text(json.dumps({"phase": phase, "as_of": cutoff}) + "\n")
        wb = Workbook()
        del wb[wb.sheetnames[0]]
        ws = wb.create_sheet("Claims")
        ws.append(["claim_id", "revision", "recorded_at", "group", "quarter", "amount_cents",
                   "priority", "review_minutes", "rail", "family", "requires_id", "status"])
        export = [r[:] for r in claims]
        if phase == 5:
            for row in claims:
                index = int(row[0].split("-")[-1])
                if index in (1, 2, 4):
                    revised = row[:]
                    revised[1:3] = [2, "2026-07-05"]
                    if index in (1, 2):
                        revised[-1] = "PAID" if index == 1 else "BLOCKED"
                    else:
                        revised[5] += 701
                        revised[6] = 1
                    export.append(revised)
            for group in groups:
                export.append([f"{group}-10", 1, "2026-07-10", group, "2026-Q1",
                               611 if group == "Exact" else 17311, 1, 8, "PORTAL", "new-choice", None, "OPEN"])
            future = export[0][:]
            future[1:3] = [999, "2026-08-01"]
            future[-1] = "BLOCKED"
            export.append(future)
        rng.shuffle(export)
        export.append(claims[0][:])
        for row in export:
            ws.append(row)
        paid = wb.create_sheet("Paid")
        paid.append(["receipt_id", "revision", "recorded_at", "group", "quarter", "amount_cents", "status"])
        for i, group in enumerate(GROUPS):
            paid.append([f"RECEIPT-{i}", 1, "2026-06-01", group, "2026-Q1", 7000 + 1300 * i, "CONFIRMED"])
            if phase == 5:
                paid.append([f"JULY-{i}", 1, "2026-07-06", group, "2026-Q1",
                             next(r[5] for r in claims if r[0] == f"{group}-01"), "CONFIRMED"])
        if phase == 5:
            paid.append(["RECEIPT-0", 2, "2026-07-08", "Aster", "2026-Q1", 7000, "VOID"])
            paid.append(["RECEIPT-0", 1, "2026-06-01", "Aster", "2026-Q1", 7000, "CONFIRMED"])
        suppliers = wb.create_sheet("Suppliers")
        suppliers.append(["group", "setup_minutes", "min_batch_cents", "max_claims"])
        for i, group in enumerate(groups):
            suppliers.append([group, 3 + 2 * i, 500 if group == "Exact" else 5000, 3 if group == "Exact" else 4])
        suppliers.append(["Legacy", 5, 5000, 4])
        rails = wb.create_sheet("Rails")
        rails.append(["rail", "max_claims"])
        rails.append(["WIRE", 8])
        rails.append(["PORTAL", 7 if phase == 4 else 5])
        limits = wb.create_sheet("Limits")
        limits.append(["name", "value"])
        limits.append(["review_minutes", 190 if phase == 4 else 170])
        wb.save(fixtures / f"claims-{phase}.xlsx")
        shutil.copyfile(fixtures / f"claims-{phase}.xlsx", work / "claims.xlsx")


if __name__ == "__main__":
    generate()
