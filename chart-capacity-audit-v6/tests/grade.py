import copy
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import traceback

from reference import WIDTH, close, expected, intervals_from_truth, reading_index

ROOT = Path(__file__).parent
COMPONENTS = ("extraction", "reconciliation", "calculations", "planning", "claims", "reproducibility")
GATES = ("protected", "extraction", "missing", "reconciliation", "calculations",
         "planning", "claims", "reproducibility", "supported_decision")
VERDICTS = ["incorrect"]*5+["correct", "incorrect", "unsupported"]


def load(path):
    def reject(value):
        raise ValueError("nonfinite JSON constant: "+value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def score(checks):
    components = {k: sum(checks.get(k, []))/len(checks[k]) if checks.get(k) else 0.0 for k in COMPONENTS}
    gates = checks.get("gates", {})
    passed = all(gates.get(k, False) for k in GATES) and all(gates.values())
    weighted = sum(components[k]*w for k, w in zip(COMPONENTS, [.2,.2,.2,.2,.1,.1]))
    return {"overall": round(weighted, 6) if passed else 0.0, **components}


def extraction(readings, truth, manifest, operations):
    indices = reading_index(readings, manifest, operations)
    checks, missing = [], []
    for kind, index, coordinate in zip(("counters", "histograms"), indices, ("boundary", "window")):
        for row in truth[kind]:
            submitted = index[row["page"], row["target"], row[coordinate]]
            fields = ("requests", "errors") if kind == "counters" else ("bins",)
            for field in fields:
                raw, got = row[field], submitted[field]
                missing.append((raw is None) == (got is None))
                if raw is None or got is None:
                    checks.append(raw is None and got is None)
                    continue
                raw_values = raw if field == "bins" else [raw]
                got_values = got if field == "bins" else [got]
                for value, interval in zip(raw_values, got_values):
                    lo, _, hi = interval
                    width = max(WIDTH["bins"],.005*sum(row["bins"])) if field == "bins" else WIDTH[field]
                    checks.append(lo-1e-8 <= value <= hi+1e-8 and hi-lo <= width+1e-8)
    return checks, all(missing)


def probes(readings, manifest, operations, planning):
    rng = random.Random(97351)
    for i in range(51):
        r, m, o, p = copy.deepcopy((readings, manifest, operations, planning))
        rng.shuffle(r["counters"])
        rng.shuffle(r["histograms"])
        rng.shuffle(m["pages"])
        if i == 1:
            m["supersedes"][0]["old"], m["supersedes"][0]["new"] = m["supersedes"][0]["new"], m["supersedes"][0]["old"]
        if i == 2:
            ids = {page["id"]: "audit-"+page["id"] for page in m["pages"]}
            for page in m["pages"]: page["id"] = ids[page["id"]]
            for edge in m["supersedes"]:
                edge["old"], edge["new"] = ids[edge["old"]], ids[edge["new"]]
            for row in r["counters"]+r["histograms"]: row["page"] = ids[row["page"]]
        if i == 3:
            o["maintenance"] = [{"target":"BS","window":"W4"}]
        if i == 4:
            for row in r["histograms"]:
                if row["target"] in ("AS", "BI"): row["bins"] = None
        if i == 5:
            p["credit_budget"] = 0
        if i == 6:
            p["minimum_latency_samples"] = 100000
        if i == 7:
            o["windows"] = o["windows"][:3]
            o["boundaries"] = o["boundaries"][:4]
            r["counters"] = [row for row in r["counters"] if row["boundary"] != "B4"]
            r["histograms"] = [row for row in r["histograms"] if row["window"] != "W4"]
        if i == 8:
            for event in o["resets"]: event["baseline"] = 50
        if i == 9:
            for row in r["counters"]:
                if row["target"] == "AS":
                    row["requests"], row["errors"] = [0,0,0], [0,0,0]
        if i == 10:
            for row in r["histograms"]:
                if row["target"] == "AI":
                    row["bins"] = [[950,950,950],[0,0,0],[50,50,50],[0,0,0]] if row["window"] == "W1" else None
        if i == 11:
            for w in o["windows"]: w["minutes"] = rng.choice([15,45,90])
            p["target_order"].reverse()
        if 12 <= i < 16:
            p["credit_budget"] = rng.randint(8, 25)
            p["power_budget"] = [3, 7, 10, 15][i-12]
            p["max_active_regions"] = [1, 2, 3, 4][i-12]
            for spec in p["regions"].values():
                spec["frozen"] = False
                spec["max_blocks"] = rng.randint(1, 4)
            factors = {t: rng.choice([.5, 1, 1.5]) for t in p["target_order"]}
            for row in r["counters"]:
                if row["errors"] is not None:
                    row["errors"] = [v*factors[row["target"]] for v in row["errors"]]
        if i == 16:
            for row in r["histograms"]:
                if row["target"] == "AI":
                    row["bins"] = [[940,950,960],[0,0,0],[40,50,60],[0,0,0]] if row["window"] == "W1" else None
        if 17 <= i < 20:
            o["resets"], o["maintenance"] = [], []
            for row in r["counters"]:
                boundary = int(row["boundary"][1:])
                row["requests"] = [boundary*10000]*3
                row["errors"] = [boundary*100]*3
            for row in r["histograms"]:
                row["bins"] = [[v]*3 for v in (500,300,150,50)]
            for j, spec in enumerate(p["targets"].values()):
                spec.update(cost=[0,1,2], power=[0,1,2], reduction=[0,.6,.8], risk_weight=j+1)
            for spec in p["regions"].values():
                spec.update(frozen=False, activation_cost=0, max_blocks=1 if i == 19 else 2)
            p.update(credit_budget=8, power_budget=1 if i == 18 else 8,
                     max_active_regions=1 if i == 17 else 4)
        e = p["execution"]
        if i == 20:
            e["crews"] = [0]*e["horizon"]
        if i == 21:
            e["crews"],e["region_gap"] = [2]*6,0
            for t in e["candidates"]:
                e["durations"][t],e["warmups"][t],e["blackouts"][t] = [1,1],[0,0],[]
            p.update(credit_budget=30,power_budget=20,max_active_regions=4)
            for region in p["regions"].values(): region["max_blocks"] = 4
        if i == 22:
            e["candidates"].reverse()
            p["target_order"].reverse()
            e["dependencies"] = [{"target":"AS","tier":1,"requires":"DS","requires_tier":1}]
        if i == 23:
            e["horizon"],e["crews"] = 4,[1,2,1,2]
            for t in e["candidates"]: e["blackouts"][t] = [s for s in e["blackouts"][t] if s < 4]
            for case in e["cases"]:
                case["exposure"] = {t:v[:4] for t,v in case["exposure"].items()}
        if i == 24:
            e["disruption"] = 1
            for case in e["cases"]:
                for t in p["target_order"]: case["exposure"][t] = [5,4,3,2,1,0]
        if i == 25:
            e["cases"].reverse()
            for j,case in enumerate(e["cases"]): case["id"] = f"forecast-{j}"
            e["links"].reverse()
        if i == 26:
            for case in e["cases"]:
                for t in p["target_order"]: case["exposure"][t] = [0]*6
        if i == 27:
            e["candidates"],e["dependencies"],e["links"] = ["AS"],[],[]
            e["durations"]["AS"],e["warmups"]["AS"],e["blackouts"]["AS"] = [1,1],[0,0],[]
            e["region_gap"],e["disruption"],e["max_jobs"] = 0,0,2
            for case in e["cases"]:
                for t in p["target_order"]: case["exposure"][t] = [0,0,0,1,2,4]
        if i == 28:
            e["crews"] = [1]*6
            e["blackouts"]["DS"] = [0,1,2]
        if i == 29:
            e["cases"] = e["cases"][:2]
            for t in p["target_order"]:
                e["cases"][0]["exposure"][t] = [3,3,3,0,0,0]
                e["cases"][1]["exposure"][t] = [0,0,0,3,3,3]
        if i == 30:
            e["candidates"] = ["AI","BS","CI","DI"]
            e["dependencies"] = []
            for t in e["candidates"]:
                e["durations"][t],e["warmups"][t],e["blackouts"][t] = [1,1],[0,0],[]
        if i == 31:
            e["dependencies"] = [
                {"target":"AS","tier":1,"requires":"DS","requires_tier":1},
                {"target":"BS","tier":1,"requires":"AS","requires_tier":1},
                {"target":"BI","tier":1,"requires":"BS","requires_tier":1}]
            for t in e["candidates"]:
                e["durations"][t],e["warmups"][t],e["blackouts"][t] = [1,1],[0,0],[]
            p["max_active_regions"],e["region_gap"] = 4,0
        if i == 32:
            e["candidates"],e["links"],e["max_jobs"] = ["AS","BS"],[],2
            e["dependencies"] = [{"target":"BS","tier":1,"requires":"AS","requires_tier":1}]
            e["durations"]["AS"],e["durations"]["BS"] = [1,1],[1,1]
            e["warmups"]["AS"],e["warmups"]["BS"] = [0,0],[0,0]
            e["blackouts"]["AS"],e["blackouts"]["BS"] = [1,2,3,4,5],[]
            e["region_gap"] = 0
            for case in e["cases"]:
                case["exposure"]["AS"] = [2,0,0,0,0,0]
                case["exposure"]["BS"] = [0,0,0,2,3,4]
        if i == 33:
            e["crews"] = [2,0,2,2,1,2]
        if i == 34:
            e["reveal"] = 0
        if i == 35:
            e["reveal"] = e["horizon"]
        if i == 36:
            e["reveal"] = 1
        if i == 37:
            e["reveal"] = 2
            e["cases"].reverse()
            e["crews"] = [2,2,2,2,2,2]
        if i == 38:
            e["reveal"] = 2
            e["region_gap"],e["max_jobs"] = 1,4
            e["dependencies"] = [{"target":"BS","tier":1,"requires":"DS","requires_tier":1}]
            e["warmups"]["DS"] = [1,1]
        if i == 39:
            e["reveal"],e["max_jobs"] = 1,2
            e["candidates"],e["dependencies"],e["links"] = ["AS","DS"],[],[]
            e["crews"],e["region_gap"],e["disruption"] = [1]*6,0,0
            for t in e["candidates"]:
                e["durations"][t],e["warmups"][t],e["blackouts"][t] = [1,1],[0,0],[]
            e["cases"] = e["cases"][:2]
            for case in e["cases"]:
                for t in p["target_order"]: case["exposure"][t] = [0]*6
            e["cases"][0]["exposure"]["AS"] = [0,0,1,1,1,1]
            e["cases"][1]["exposure"]["DS"] = [0,0,1,1,1,1]
            p["credit_budget"] = 8
        if i == 40:
            e["reveal"] = 0
            e["cases"] = e["cases"][:1]
        if i == 41:
            e["signals"].update(coarse_at=0,exact_at=0)
        if i == 42:
            e["signals"].update(coarse_at=0,exact_at=6,groups=["same"]*3)
        if i == 43:
            e["signals"].update(coarse_at=2,exact_at=4,groups=["x","y","x"])
        if i == 44:
            e["signals"].update(coarse_at=1,exact_at=5,groups=["x","y","z"])
        if i == 45:
            e["signals"].update(coarse_at=1,exact_at=3,groups=["same"]*3)
        if i == 46:
            e["signals"].update(coarse_at=3,exact_at=3)
        if i == 47:
            e["cases"][2]["exposure"] = {t:[v*.25 for v in values]
                                        for t,values in e["cases"][2]["exposure"].items()}
        if i == 48:
            e["signals"]["sum_weight"] = 0
        if i == 49:
            e["signals"]["sum_weight"] = .5
        if i == 50:
            e["signals"]["coarse_at"] = 0
            forecast_rng = random.Random(0)
            for j,case in enumerate(e["cases"]):
                for t in p["target_order"]:
                    values = [forecast_rng.randint(0,8) for _ in range(6)]
                    case["exposure"][t] = [v/10 for v in values] if j == 2 else values
        e["signals"]["groups"] = e["signals"]["groups"][:len(e["cases"])]
        yield r, m, o, p


def invalid_probes(readings, manifest, operations, planning):
    for i in range(25):
        r, m, o, p = copy.deepcopy((readings, manifest, operations, planning))
        if i == 0: r["counters"].append(r["counters"][0])
        if i == 1: r["counters"].pop()
        if i == 2: r["units"] = "thousands"
        if i == 3: r["counters"][0]["page"] = "nonexistent"
        if i == 4: r["counters"][0]["errors"] = [5,4,3]
        if i == 5: r["counters"][0]["errors"] = [-1,0,1]
        if i == 6: m["supersedes"].append({"old":"C2.r2","new":"C2.r1","scope":"whole page"})
        if i == 7: o["resets"] = [e for e in o["resets"] if not(e["target"] == "AS" and e["metric"] == "errors")]
        if i == 8: r["histograms"][0]["bins"] = [[1,1,1]]*3
        if i == 9: r["counters"][0]["errors"] = [1,float("nan"),3]
        e = p["execution"]
        if i == 10: e["horizon"] = 7
        if i == 11: e["crews"].pop()
        if i == 12: e["cases"][0]["exposure"]["AS"].pop()
        if i == 13: e["cases"][0]["exposure"]["AS"][0] = -1
        if i == 14: e["durations"]["AS"][0] = 0
        if i == 15: e["blackouts"]["AS"] = [6]
        if i == 16: e["candidates"][0] = "invalid-target"
        if i == 17:
            e["dependencies"] = [{"target":"AS","tier":1,"requires":"AS","requires_tier":2}]
        if i == 18: e["reveal"] = -1
        if i == 19: e["reveal"] = e["horizon"]+1
        if i == 20: e["reveal"] = 1.5
        if i == 21: e["signals"]["coarse_at"] = e["signals"]["exact_at"]+1
        if i == 22: e["signals"]["groups"].pop()
        if i == 23: e["signals"]["exact_at"] = 6.5
        if i == 24: e["signals"]["sum_weight"] = -1
        yield r, m, o, p


def execute(script, data, registry, folder):
    folder.mkdir()
    args = [sys.executable, str(script)]
    for key, value in zip(("readings", "manifest", "operations", "planning"), data):
        path = folder/(key+".json")
        path.write_text(json.dumps(value))
        args += ["--"+key, str(path)]
    reg = folder/"registry.csv"
    reg.write_text(registry)
    output = folder/"result.json"
    args += ["--registry", str(reg), "--out", str(output)]
    run = subprocess.run(args, cwd=folder, capture_output=True, text=True, timeout=90)
    return run, output


def grade(app, log):
    checks = {"gates": {}}
    details = {"checks": checks, "errors": []}
    try:
        manifest = load(app/"export-manifest.json")
        operations = load(app/"operations.json")
        planning = load(app/"planning.json")
        truth = load(ROOT/"truth.json")
        submission = app/"submission"
        checks["gates"]["protected"] = all(hashlib.sha256((app/f).read_bytes()).hexdigest() == digest
                                            for f, digest in load(ROOT/"protected.json").items())
        readings, output = load(submission/"readings.json"), load(submission/"analysis.json")
        checks["extraction"], checks["gates"]["missing"] = extraction(readings, truth, manifest, operations)
        checks["gates"]["extraction"] = sum(checks["extraction"])/len(checks["extraction"]) >= .98
        want = expected(readings, manifest, operations, planning)
        checks["reconciliation"] = [close(output.get("inventory"), want["inventory"])]
        actual_rows = output.get("intervals", [])
        checks["reconciliation"] += [len(actual_rows) == len(want["intervals"]) and
                                     close(actual_rows[i], row) for i, row in enumerate(want["intervals"])]
        checks["calculations"] = [close(output.get("targets", {}).get(t), s) for t, s in want["targets"].items()]
        checks["calculations"].append(close(output.get("fleet"), want["fleet"]))
        checks["planning"] = [close(output.get("plan"), want["plan"])]
        scenarios = output.get("scenarios", [])
        checks["planning"] += [len(scenarios) == 2 and close(scenarios[i], s) for i, s in enumerate(want["scenarios"])]
        checks["planning"].append(close(output.get("execution"), want["execution"]))
        exact = expected(intervals_from_truth(truth, 0), manifest, operations, planning)
        checks["gates"]["supported_decision"] = (
            close(output.get("plan", {}).get("tiers"), exact["plan"]["tiers"]) and
            output.get("plan", {}).get("robust") is True and
            all(output.get("targets", {}).get(t, {}).get("latency_eligible") == s["latency_eligible"]
                for t, s in exact["targets"].items()))
        claims = load(submission/"audit.json")["claims"]
        by_id = {row["id"]: row for row in claims}
        specs = load(app/"draft-review.json")["claims"]
        assert len(by_id) == len(claims) == len(specs) and set(by_id) == {c["id"] for c in specs}
        valid_sources = {page["id"] for page in manifest["pages"]} | {
            "operations.json","planning.json","export-manifest.json","corrections.md","registry.csv","policy.md"}
        checks["claims"] = []
        for spec, verdict in zip(specs, VERDICTS):
            row = by_id[spec["id"]]
            checks["claims"].append(
                row.get("verdict") == verdict and isinstance(row.get("evidence"), list) and
                set(spec["required_evidence"]) <= set(row["evidence"]) <= valid_sources and
                isinstance(row.get("explanation"), str) and bool(row["explanation"].strip()))
        script = submission/"analyze.py"
        registry = (app/"registry.csv").read_text()
        data = readings, manifest, operations, planning
        with tempfile.TemporaryDirectory(prefix="chart-v2-probe-") as temp:
            base = Path(temp)
            run, path = execute(script, data, registry, base/"original")
            original = run.returncode == 0 and path.exists() and close(load(path), want)
            valid, invalid = [], []
            for index, probe in enumerate(probes(*data)):
                run, path = execute(script, probe, registry, base/f"valid-{index}")
                ok = run.returncode == 0 and path.exists() and close(load(path), expected(*probe))
                valid.append(ok)
                if not ok:
                    details["errors"].append({"probe": index, "exit": run.returncode, "stderr": run.stderr[-1000:]})
            for index, probe in enumerate(invalid_probes(*data)):
                run, _ = execute(script, probe, registry, base/f"invalid-{index}")
                invalid.append(run.returncode != 0 and bool((run.stdout+run.stderr).strip()))
        details.update(counterfactuals=valid, invalid_inputs=invalid)
        report = submission/"decision.md"
        checks["reproducibility"] = [original, all(valid), all(invalid), report.exists() and bool(report.read_text().strip())]
        for component in ("reconciliation", "calculations", "planning", "claims", "reproducibility"):
            checks["gates"][component] = all(checks[component])
    except (AssertionError, ValueError, TypeError, KeyError, IndexError, OSError, subprocess.SubprocessError):
        checks["gates"]["evaluation_complete"] = False
        details["errors"].append(traceback.format_exc())
    reward = score(checks)
    (log/"reward.json").write_text(json.dumps(reward, indent=2)+"\n")
    (log/"details.json").write_text(json.dumps(details, indent=2)+"\n")
    print(json.dumps(reward), flush=True)
    return 0 if reward["overall"] > 0 else 1


if __name__ == "__main__":
    log = Path(os.environ.get("VERIFIER_LOG", "/logs/verifier"))
    log.mkdir(parents=True, exist_ok=True)
    (log/"reward.json").write_text(json.dumps({"overall": 0.0, **dict.fromkeys(COMPONENTS, 0.0)}))
    raise SystemExit(grade(Path(os.environ.get("APP_ROOT", "/app")), log))
