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

from reference import METRICS, SOURCES, equivalent, expected, records_by_key, truth_observations

ROOT = Path(__file__).parent
CLAIMS = {"D1": "incorrect", "D2": "incorrect", "D3": "incorrect",
          "D4": "incorrect", "D5": "correct", "D6": "unsupported"}
PANELS = {"D1": {"P1", "P2", "P4"}, "D2": {"P1", "P2", "P4"}, "D3": {"P4"},
          "D4": {"P1", "P4"}, "D5": {"P3", "P4"}, "D6": {"P2", "P4"}}
ALLOCATION_KEYS = ("allocation", "expected_benefit", "benefit_bounds", "robust_margin", "robust")
COMPONENTS = ("extraction", "calculations", "allocation", "claim_audit", "reproducibility")
GATES = ("protected_inputs", "statuses", "citations", "supported_allocation",
         "reading_envelope", "critical_claims", "calculations", "allocation", "reproducibility")


def load(path):
    def reject(value):
        raise ValueError(f"nonfinite JSON number: {value}")
    return json.loads(Path(path).read_text(), parse_constant=reject)


def calculate_reward(checks):
    components = {}
    for key in COMPONENTS:
        values = checks.get(key, [])
        components[key] = sum(values)/len(values) if values else 0.0
    gates = checks.get("gates", {})
    gate = all(gates.get(name, False) for name in GATES) and all(gates.values())
    weights = dict(zip(COMPONENTS, (.25, .25, .20, .15, .15)))
    return {"overall": round(sum(weights[k]*v for k, v in components.items()), 6) if gate else 0.0,
            **components}


def counterfactuals(observations, policy):
    rng = random.Random(517023)
    for index in range(12):
        obs, pol = copy.deepcopy(observations), copy.deepcopy(policy)
        pol["budget_blocks"] = index % 7
        pol["latency_trigger_ms"] = [250, 300, 350, 450][index % 4]
        pol["max_blocks_per_region"] = 1 if index % 3 == 0 else 2
        pol["benefit_fraction"] = [0, .35] if pol["max_blocks_per_region"] == 1 else [0, .3, .55]
        for window in pol["windows"]:
            window["minutes"] = rng.choice([15, 30, 45, 60])
        for row in obs["records"]:
            row["status"] = rng.choice(["normal", "normal", "normal", "maintenance", "unknown"])
            for name in METRICS:
                if row["status"] == "unknown":
                    row[name] = None
                else:
                    center = {"rate": rng.randint(0, 3000), "failure_pct": rng.randint(0, 40)/4,
                              "p95_ms": rng.randint(240, 460)}[name]
                    delta = {"rate": 30, "failure_pct": .1, "p95_ms": 2}[name]
                    row[name] = [max(0, center-delta), center, center+delta]
        if index in (9, 10):
            for row in obs["records"]:
                row["status"] = "normal"
                row["rate"] = [0, 0, 0] if index == 9 else [100, 100, 100]
                row["failure_pct"] = [1, 1, 1]
                row["p95_ms"] = [440, 440, 440]
        if index == 11:
            pol["windows"] = pol["windows"][:1]
            obs["records"] = [r for r in obs["records"] if r["window"] == pol["windows"][0]["id"]]
        rng.shuffle(obs["records"])
        yield obs, pol


def run_program(script, observations, policy, directory, label):
    folder = directory / label
    folder.mkdir()
    obs, pol, out = folder/"readings.json", folder/"settings.json", folder/"result.json"
    obs.write_text(json.dumps(observations))
    pol.write_text(json.dumps(policy))
    result = subprocess.run([sys.executable, str(script), "--observations", str(obs),
                             "--policy", str(pol), "--out", str(out)],
                            cwd=folder, text=True, capture_output=True, timeout=15)
    (folder/"stdout.txt").write_text(result.stdout)
    (folder/"stderr.txt").write_text(result.stderr)
    return result, out


def audit_checks(audit, policy):
    rows = audit["claims"]
    assert len(rows) == len(CLAIMS) and {r["id"] for r in rows} == set(CLAIMS)
    result = {}
    windows = {w["id"] for w in policy["windows"]}
    for row in rows:
        cid = row["id"]
        refs = row["evidence"]
        valid = bool(refs) and all(
            isinstance(ref, dict) and ref.get("panel") in SOURCES.values() and
            ref.get("region") in policy["regions"] and ref.get("window") in windows for ref in refs)
        valid = valid and PANELS[cid] <= {ref["panel"] for ref in refs}
        coordinates = {(ref.get("region"), ref.get("window")) for ref in refs}
        if cid == "D3":
            valid = valid and bool(coordinates & {("Delta", "W1"), ("Delta", "W2")})
        if cid == "D4":
            valid = valid and bool(coordinates & {("Cedar", "W7"), ("Cedar", "W8")})
        if cid == "D5":
            valid = valid and {("Cedar", "W5"), ("Cedar", "W6")} <= coordinates
        if cid == "D6":
            valid = valid and {("Birch", "W4"), ("Birch", "W5")} <= coordinates
        result[cid] = bool(valid and row["verdict"] == CLAIMS[cid] and
                           isinstance(row.get("explanation"), str) and row["explanation"].strip())
    return result


def grade(app, log):
    submission = app/"submission"
    checks = {}
    details = {"checks": checks, "errors": []}
    truth = load(ROOT/"truth.json")
    policy = load(app/"policy.json")
    protected = load(ROOT/"protected.json")
    intact = all(hashlib.sha256((app/name).read_bytes()).hexdigest() == digest
                 for name, digest in protected.items())
    checks["gates"] = {"protected_inputs": intact}
    try:
        observations = load(submission/"observations.json")
        records = records_by_key(observations, policy)
        raw = {(r["region"], r["window"]): r for r in truth["records"]}
        statuses, citations, extraction = [], [], []
        for key, target in raw.items():
            row = records[key]
            statuses.append(row["status"] == target["status"])
            citations.append(row.get("sources") == SOURCES)
            correct = statuses[-1] and citations[-1]
            for name, width in METRICS.items():
                if target[name] is None:
                    correct = correct and row[name] is None
                elif row[name] is None:
                    correct = False
                else:
                    lo, _, hi = row[name]
                    correct = correct and lo-1e-9 <= target[name] <= hi+1e-9 and hi-lo <= width+1e-9
            extraction.append(bool(correct))
        checks["extraction"] = extraction
        checks["gates"].update(statuses=all(statuses), citations=all(citations))
        want = expected(observations, policy)
        actual = load(submission/"analysis.json")
        checks["calculations"] = [
            equivalent(actual.get("regions", {}).get(r), want["regions"][r]) for r in policy["regions"]
        ] + [equivalent(actual.get("fleet"), want["fleet"])]
        checks["allocation"] = [all(equivalent(actual.get(k), want[k]) for k in ALLOCATION_KEYS)]
        exact = expected(truth_observations(truth), policy)
        checks["gates"]["supported_allocation"] = (equivalent(actual.get("allocation"), exact["allocation"]) and
                                                  actual.get("robust") is True)
        # Any admissible interval can extend at most one full width from the true
        # value. Use that envelope, not an artificially precise exact-data check.
        envelope = truth_observations(truth, METRICS)
        bounds = expected(envelope, policy)
        checks["gates"]["reading_envelope"] = all(
            bounds["regions"][r]["failed_bounds"][0]-1e-6 <= want["regions"][r]["failed_requests"]
            <= bounds["regions"][r]["failed_bounds"][1]+1e-6 for r in policy["regions"])
        for region in policy["regions"]:
            selected = [w for w in policy["windows"] if raw[region, w["id"]]["status"] == "normal"]
            low = sum(w["minutes"]*max(0, raw[region, w["id"]]["rate"]-100) for w in selected)
            high = sum(w["minutes"]*(raw[region, w["id"]]["rate"]+100) for w in selected)
            checks["gates"]["reading_envelope"] &= low-1e-6 <= want["regions"][region]["requests"] <= high+1e-6
        claims = audit_checks(load(submission/"audit.json"), policy)
        checks["claim_audit"] = list(claims.values())
        details["claim_results"] = claims
        checks["gates"]["critical_claims"] = all(claims[k] for k in ("D1", "D2", "D3", "D4", "D6"))
        script = submission/"analyze.py"
        with tempfile.TemporaryDirectory(prefix="chart-verifier-") as tmp:
            directory = Path(tmp)
            result, out = run_program(script, observations, policy, directory, "original")
            fresh = result.returncode == 0 and out.exists() and equivalent(load(out), want)
            probes = []
            for i, (obs, pol) in enumerate(counterfactuals(observations, policy)):
                result, out = run_program(script, obs, pol, directory, f"probe-{i}")
                ok = result.returncode == 0 and out.exists() and equivalent(load(out), expected(obs, pol))
                probes.append(ok)
                if not ok:
                    details["errors"].append({"probe": i, "exit": result.returncode,
                                              "stderr": result.stderr[-2000:]})
            invalid = []
            for i in range(5):
                obs = copy.deepcopy(observations)
                if i == 0: obs["records"].pop()
                if i == 1: obs["records"].append(obs["records"][0])
                if i == 2: obs["records"][0]["status"] = "made-up"
                if i == 3: obs["records"][0]["rate"] = [-1, 0, 1]
                if i == 4: obs["records"][0]["failure_pct"] = [0, 200, 200]
                result, _ = run_program(script, obs, policy, directory, f"invalid-{i}")
                invalid.append(result.returncode != 0 and bool((result.stderr+result.stdout).strip()))
        details["counterfactuals"] = probes
        details["invalid_inputs"] = invalid
        report = submission/"audit.md"
        checks["reproducibility"] = [fresh, all(probes), all(invalid),
                                     report.exists() and bool(report.read_text().strip())]
        checks["gates"].update(calculations=all(checks["calculations"]), allocation=all(checks["allocation"]),
                               reproducibility=all(checks["reproducibility"]))
    except (AssertionError, ValueError, KeyError, TypeError, IndexError, OSError, subprocess.SubprocessError):
        checks["gates"]["complete_evaluation"] = False
        details["errors"].append(traceback.format_exc())
    reward = calculate_reward(checks)
    (log/"details.json").write_text(json.dumps(details, indent=2)+"\n")
    (log/"reward.json").write_text(json.dumps(reward, indent=2)+"\n")
    print(json.dumps(reward), flush=True)
    return 0 if reward["overall"] == 1 else 1


if __name__ == "__main__":
    log = Path(os.environ.get("VERIFIER_LOG", "/logs/verifier"))
    log.mkdir(parents=True, exist_ok=True)
    (log/"reward.json").write_text(json.dumps({"overall": 0.0, **dict.fromkeys(COMPONENTS, 0.0)}))
    raise SystemExit(grade(Path(os.environ.get("APP_ROOT", "/app")), log))
