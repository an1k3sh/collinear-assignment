import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def replace(source, old, new):
    assert source.count(old) == 1, (old,source.count(old))
    return source.replace(old,new,1)


def variants(source):
    yield "oracle", source, 1
    yield "approximate-readings", source, 1
    yield "reordered-readings", source, 1
    yield "one-reading-error-within-allowance", source, .999123
    yield "five-reading-errors", source, 0
    yield "obsolete-revision", replace(source, "selected = sorted(set(pages)-set(edges))",
        'selected = sorted((set(pages)-set(edges)-{"C2.r2"}) | {"C2.r1"})'), 0
    yield "clamp-reset-to-zero", replace(replace(source,
        'require(end[1] >= start[1], "undocumented negative counter delta")',
        'end = [max(a,b) for a,b in zip(end,start)]'),
        'start = [resets[key]]*3 if key in resets else counters[source["counters"], target, w["start"]][metric]',
        'start = counters[source["counters"], target, w["start"]][metric]'), 0
    yield "reset-both-metrics", replace(source,
        'start = [resets[key]]*3 if key in resets else counters[source["counters"], target, w["start"]][metric]',
        'start = [0]*3 if any(k[:2] == key[:2] for k in resets) else counters[source["counters"], target, w["start"]][metric]'), 0
    yield "drop-recovered-window", replace(source,
        'values[metric] = subtract(end, start)',
        'values[metric] = None if counters[source["counters"], target, w["start"]][metric] is None else subtract(end,start)'), 0
    yield "multiply-count-by-duration", replace(source,
        'values[metric] = subtract(end, start)',
        'values[metric] = subtract(end,start)\n'
        '                if values[metric] is not None: values[metric] = [v*w["minutes"] for v in values[metric]]'), 0
    yield "maintenance-latency-included", replace(source,
        'included = reason == "usable" and histogram is not None',
        'included = histogram is not None'), 0
    yield "average-window-fractions", replace(source,
        'slow = sum(pooled[2:])/samples if samples else None',
        'slow = (sum(sum(v[1] for v in histograms[source["histograms"],target,w][2:]) / '
        'sum(v[1] for v in histograms[source["histograms"],target,w]) for w in joined)/len(joined)) if joined else None'), 0
    yield "ignore-region-freeze", replace(source,
        '"rollout_eligible": eligible and not frozen', '"rollout_eligible": eligible'), 0
    yield "omit-activation-charge", replace(source,
        'credits += sum(planning["regions"][r]["activation_cost"] for r in active)',
        'credits += 0'), 0
    yield "ignore-power", replace(source,
        'if credits > budget or power > planning["power_budget"]:', 'if credits > budget:'), 0
    yield "ignore-active-region-limit", replace(source,
        'if len(active) > planning["max_active_regions"]:', 'if False:'), 0
    yield "ignore-regional-block-cap", replace(source,
        'if any(sum(k for t, k in zip(order, vector) if planning["targets"][t]["region"] == r)',
        'if False and any(sum(k for t, k in zip(order, vector) if planning["targets"][t]["region"] == r)'), 0
    yield "force-robust-success", replace(source,
        'robust=(not margins or min(margins) > 0) and all(s["eligibility_stable"] for s in summaries.values())',
        'robust=True'), 0
    yield "causal-overclaim", source, 0
    yield "static-program", source, 0
    yield "baseline", None, 0


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True,exist_ok=True)
    source = (ROOT/"solution/analyze.py").read_text()
    summary = {}
    controls = list(variants(source))
    selected = set(sys.argv[2:])
    unknown = selected-{name for name,_,_ in controls}
    if unknown:
        raise ValueError("unknown controls: "+", ".join(sorted(unknown)))
    for name, code, wanted in controls:
        if selected and name not in selected:
            continue
        with tempfile.TemporaryDirectory(prefix="chart-v2-author-") as tmp:
            app = Path(tmp)/"app"
            shutil.copytree(ROOT/"environment/app",app)
            sub = app/"submission"
            sub.mkdir()
            initial = None
            if code is not None:
                for filename in ("readings.json","audit.json","decision.md","schedule.py"):
                    shutil.copyfile(ROOT/"solution"/filename,sub/filename)
                if name in ("approximate-readings","reordered-readings"):
                    readings = json.loads((sub/"readings.json").read_text())
                    if name == "reordered-readings":
                        readings["counters"].reverse()
                        readings["histograms"].reverse()
                    else:
                        for row in readings["counters"]:
                            for metric, offset in (("requests",100),("errors",2)):
                                if row[metric] is not None: row[metric][1] += offset
                        for row in readings["histograms"]:
                            if row["bins"] is not None:
                                for interval in row["bins"]: interval[1] += 1
                    (sub/"readings.json").write_text(json.dumps(readings))
                if name == "causal-overclaim":
                    audit = json.loads((sub/"audit.json").read_text())
                    audit["claims"][-1]["verdict"] = "correct"
                    (sub/"audit.json").write_text(json.dumps(audit))
                if name in ("one-reading-error-within-allowance","five-reading-errors"):
                    readings = json.loads((sub/"readings.json").read_text())
                    count = 1 if name == "one-reading-error-within-allowance" else 5
                    for row in readings["counters"][:count]:
                        row["requests"] = [v+3000 for v in row["requests"]]
                    (sub/"readings.json").write_text(json.dumps(readings))
                script = sub/"analyze.py"
                script.write_text(code)
                py_compile.compile(str(script),doraise=True)
                args = [sys.executable,str(script),"--readings",str(sub/"readings.json"),
                        "--manifest",str(app/"export-manifest.json"),"--operations",str(app/"operations.json"),
                        "--planning",str(app/"planning.json"),"--registry",str(app/"registry.csv"),
                        "--out",str(sub/"analysis.json")]
                initial = subprocess.run(args,capture_output=True,text=True,timeout=90)
                if initial.returncode:
                    # A runtime exception is recorded, never mistaken for a
                    # successful mutant execution or discarded from the audit.
                    (out/(name+"-initial-error.log")).write_text(initial.stderr)
                if name == "static-program":
                    analysis = json.loads((sub/"analysis.json").read_text())
                    script.write_text('import sys,json\nfrom pathlib import Path\n'
                        f'answer=json.loads({json.dumps(analysis)!r})\n'
                        'Path(sys.argv[sys.argv.index("--out")+1]).write_text(json.dumps(answer))\n')
            log = out/name
            run = subprocess.run([sys.executable,str(ROOT/"tests/grade.py")],
                                 env=dict(os.environ,APP_ROOT=str(app),VERIFIER_LOG=str(log)),
                                 capture_output=True,text=True,timeout=1800)
            (out/(name+".log")).write_text(run.stdout+run.stderr)
            reward = json.loads((log/"reward.json").read_text())
            summary[name] = {"reward":reward,"expected":wanted,"exit":run.returncode,
                             "initial_exit":initial.returncode if initial else None}
            (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
            print(name,json.dumps(reward),flush=True)
            assert reward["overall"] == wanted and (run.returncode == 0) == bool(wanted),name
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
