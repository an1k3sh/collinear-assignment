"""Independent cross-process tests of the documented checkpoint protocol."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import traceback
from typing import Any

from test_semantics import APP, equal, event, successful_structure

SENTINEL = b'{"previous":"durable-output"}\n'
INVENTORY = {"warehouses": {"east": {"gear": 20, "seal": 10}, "west": {}}}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def seal(obj: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in obj.items() if key != "checksum"}
    return dict(body, checksum=digest(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")))


def checkpoint(path: Path, source: Path, incoming: Path,
               library: Path | None = None) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if set(obj) != {"format", "version", "identity", "label", "pause_count", "state", "checksum"}:
        raise AssertionError("Unexpected checkpoint envelope fields")
    equal(obj["format"], "stockroom-continuation", "format")
    equal(obj["version"], 1, "version")
    if type(obj["version"]) is not int or type(obj["pause_count"]) is not int or obj["pause_count"] < 1:
        raise AssertionError("Invalid checkpoint counters")
    if not isinstance(obj["label"], str) or not isinstance(obj["state"], dict) or not obj["state"]:
        raise AssertionError("Invalid label/state")
    equal(obj["checksum"], seal(obj)["checksum"], "canonical checksum")
    equal(obj["identity"], {"program": digest(source.read_bytes()),
                            "inventory": digest(incoming.read_bytes()),
                            "library": digest(library.read_bytes()) if library else None},
          "content fingerprints")
    return obj


def invoke(source: Path, incoming: Path, output: Path, *, library=None,
           save=None, resume=None) -> subprocess.CompletedProcess:
    args = [sys.executable, "-m", "stockroom", str(source),
            "--inventory", str(incoming), "--out", str(output)]
    if library:
        args += ["--library", str(library)]
    if save:
        args += ["--checkpoint", str(save)]
    if resume:
        args += ["--resume", str(resume)]
    return subprocess.run(args, cwd=APP, capture_output=True, text=True, timeout=15)


def status(process, expected):
    equal(process.returncode, expected, f"return code; stderr={process.stderr}")
    if expected in {0, 10} and process.stderr.strip():
        raise AssertionError(f"Unexpected success diagnostic: {process.stderr}")


def diagnostic(process, category, code):
    equal(process.returncode, code, f"return code; stderr={process.stderr}")
    lines = process.stderr.strip().splitlines()
    if len(lines) != 1:
        raise AssertionError("Expected one diagnostic")
    obj = json.loads(lines[0])
    equal(obj.get("error"), category, "diagnostic category")
    if not isinstance(obj.get("message"), str) or not obj["message"]:
        raise AssertionError("Missing diagnostic message")
    return obj


def setup(root: Path, source: str, library: str | None = None):
    root.mkdir()
    program, incoming = root / "program.stock", root / "inventory.json"
    program.write_text(source, encoding="utf-8")
    incoming.write_text(json.dumps(INVENTORY), encoding="utf-8")
    lib = root / "library.stock" if library is not None else None
    if lib:
        lib.write_text(library, encoding="utf-8")
    return program, incoming, lib


def compare_runs(source: str, labels: list[str], *, expected_events=None,
                 expected_stats=None, expected_warehouses=None, expected_holds=None,
                 library: str | None = None, expected_failure=None):
    with tempfile.TemporaryDirectory(prefix="stockroom-durable-check-") as directory:
        root = Path(directory)
        program, incoming, lib = setup(root / "run0", source, library)
        baseline = root / "uninterrupted.json"
        baseline.write_bytes(SENTINEL)
        normal = invoke(program, incoming, baseline, library=lib)
        if expected_failure:
            category, code = expected_failure
            normal_diag = diagnostic(normal, category, code)
            equal(baseline.read_bytes().hex(), SENTINEL.hex(), "uninterrupted failure atomicity")
        else:
            status(normal, 0)
            normal_result = json.loads(baseline.read_text())
            successful_structure(normal_result)
            if expected_events is not None:
                equal(normal_result["events"], [dict(e, id=i) for i, e in enumerate(expected_events, 1)],
                      "hand-witness events")
            if expected_stats is not None:
                equal(normal_result["stats"], expected_stats, "hand-witness counters")
            if expected_warehouses is not None:
                equal(normal_result["warehouses"], expected_warehouses, "hand-witness inventory")
            if expected_holds is not None:
                equal(normal_result["holds"], expected_holds, "hand-witness holds")
        output = program.parent / "result.json"
        output.write_bytes(SENTINEL)
        save = program.parent / "checkpoint.json"
        save.write_bytes(b'{"old":"checkpoint"}\n')
        process = invoke(program, incoming, output, library=lib, save=save)
        last_bytes = None
        last_inputs = None
        for index, label in enumerate(labels, 1):
            status(process, 10)
            equal(output.read_bytes().hex(), SENTINEL.hex(), "pause changed result")
            obj = checkpoint(save, program, incoming, lib)
            equal(obj["label"], label, "pause label")
            equal(obj["pause_count"], index, "cumulative pause count")
            old_root = program.parent
            new_root = root / f"run{index}"
            new_root.mkdir()
            new_program, new_input = new_root / program.name, new_root / incoming.name
            new_save, new_output = new_root / "checkpoint.json", new_root / "result.json"
            for old, new in [(program, new_program), (incoming, new_input), (save, new_save)]:
                shutil.copyfile(old, new)
            new_lib = new_root / lib.name if lib else None
            if new_lib:
                shutil.copyfile(lib, new_lib)
            shutil.rmtree(old_root)
            program, incoming, lib = new_program, new_input, new_lib
            save, output = new_save, new_output
            output.write_bytes(SENTINEL)
            last_bytes = save.read_bytes()
            last_inputs = (program.read_bytes(), incoming.read_bytes(),
                           lib.read_bytes() if lib else None)
            process = invoke(program, incoming, output, library=lib, resume=save)
        if expected_failure:
            category, code = expected_failure
            resumed_diag = diagnostic(process, category, code)
            for key in ("error", "code", "stack", "line", "column"):
                if key in normal_diag:
                    equal(resumed_diag.get(key), normal_diag[key], f"resumed diagnostic {key}")
            equal(output.read_bytes().hex(), SENTINEL.hex(), "resumed failure publication")
        else:
            status(process, 0)
            resumed = json.loads(output.read_text())
            equal(resumed, normal_result, "interrupted/uninterrupted equivalence")
        if last_bytes is not None:
            equal(save.read_bytes().hex(), last_bytes.hex(), "completion changed checkpoint")
            if (program.read_bytes(), incoming.read_bytes(), lib.read_bytes() if lib else None) != last_inputs:
                raise AssertionError("Source mutation")
            replay = program.parent / "replay.json"
            replay.write_bytes(SENTINEL)
            again = invoke(program, incoming, replay, library=lib, resume=save)
            if expected_failure:
                diagnostic(again, expected_failure[0], expected_failure[1])
                equal(replay.read_bytes().hex(), SENTINEL.hex(), "failed replay publication")
            else:
                status(again, 0)
                equal(json.loads(replay.read_text()), normal_result, "immutable snapshot replay")


def continuation_cases():
    yield "pause-not-a-commit-and-counters", lambda: compare_runs('''
proc main() {
 let x:int=1;
 transaction {
   set x=2; reserve("h","east","gear",3);
   emit "discarded" {}; pause "approval"; assert false;
 } recover(e) { emit code(e) {x:x;}; }
}
''', ["approval"], expected_events=[event("ASSERT", x=1)],
        expected_stats={"steps": 8, "committed": 0, "rolled_back": 1},
        expected_warehouses=INVENTORY["warehouses"], expected_holds={})
    yield "nested-commit-before-pause-outer-abort", lambda: compare_runs('''
proc main() {
 let x:int=0;
 transaction {
   transaction { set x=7; receive("west","gear",4); emit "inner" {}; }
   pause "inner-committed"; assert false;
 } recover(e) { pause code(e); emit "outer" {x:x;}; }
}
''', ["inner-committed", "ASSERT"], expected_events=[event("outer", x=0)],
        expected_stats={"steps": 10, "committed": 1, "rolled_back": 1},
        expected_warehouses=INVENTORY["warehouses"], expected_holds={})
    yield "pause-in-callee-and-return", lambda: compare_runs('''
proc worker(n:int=3) {
 transaction {
   reserve("h","east","gear",n); pause "callee";
   ship("h",n); emit "shipped" {n:n;}; return;
 }
}
proc main() { worker(); emit "end" {}; }
''', ["callee"], expected_events=[event("shipped", n=3), event("end")],
        expected_stats={"steps": 8, "committed": 1, "rolled_back": 0})
    yield "caller-rollback-after-resumed-return", lambda: compare_runs('''
proc worker() { transaction { pause "worker"; emit "gone" {}; return; } }
proc main() {
 transaction { worker(); pause "caller"; assert false; }
 recover(e) { emit "kept" {}; }
}
''', ["worker", "caller"], expected_events=[event("kept")],
        expected_stats={"steps": 9, "committed": 1, "rolled_back": 1})
    yield "repeated-label-loop-continue-break", lambda: compare_runs('''
proc main() {
 let i:int=0;
 while(i<5) {
   set i=i+1;
   transaction {
     pause "repeat"; receive("west","gear",1);
     if(i==1) {continue;}
     if(i==3) {break;}
     emit "middle" {i:i;};
   }
 }
 emit "end" {i:i;};
}
''', ["repeat"] * 3, expected_events=[event("middle", i=2), event("end", i=3)],
        expected_stats={"steps": 23, "committed": 3, "rolled_back": 0},
        expected_warehouses={"east": INVENTORY["warehouses"]["east"], "west": {"gear": 3}})
    yield "pause-in-loop-body-before-declarations", lambda: compare_runs('''
proc main() {
 let i:int=0;
 while(i<3) {
   pause ""; let local:int=i; set i=i+1;
   emit "loop" {local:local;};
 }
}
''', [""] * 3, expected_events=[event("loop", local=i) for i in range(3)])
    yield "nested-recovery-error-shadowing", lambda: compare_runs('''
proc main() {
 let e:string="outside";
 transaction { assert false; } recover(e) {
   pause code(e);
   if(true) { let e:string="shadow"; pause e; emit e {}; }
   transaction { ship("missing",1); } recover(inner) {
     pause code(inner); emit "two" {a:code(e); b:code(inner);};
   }
   emit code(e) {};
 }
 emit e {};
}
''', ["ASSERT", "shadow", "HOLD"],
        expected_events=[event("shadow"), event("two", a="ASSERT", b="HOLD"),
                         event("ASSERT"), event("outside")])
    yield "paused-recovery-undone-by-outer", lambda: compare_runs('''
proc main() {
 let x:int=0;
 transaction {
   transaction { assert false; } recover(e) {
     set x=9; receive("west","gear",3); emit "gone" {}; pause code(e);
   }
   pause "before-outer-failure"; assert false;
 } recover(e) { emit "outer" {x:x;}; }
}
''', ["ASSERT", "before-outer-failure"], expected_events=[event("outer", x=0)],
        expected_warehouses=INVENTORY["warehouses"], expected_holds={})
    yield "inner-recovery-failure-after-resume", lambda: compare_runs('''
proc main() {
 transaction {
   transaction { assert false; } recover(e) {
     pause code(e); receive("west","gear",8); assert false;
   }
 } recover(outer) { emit code(outer) {}; }
}
''', ["ASSERT"], expected_events=[event("ASSERT")],
        expected_warehouses=INVENTORY["warehouses"], expected_holds={})
    yield "shadowed-bindings-survive-two-rollbacks", lambda: compare_runs('''
proc main() {
 let x:int=1;
 transaction {
   set x=2;
   if(true) {
     let x:int=10;
     transaction { set x=99; pause "inner"; assert false; }
     recover(e) { pause "inner-recovery"; emit "inner" {x:x;}; }
   }
   pause "outer"; assert false;
 } recover(e) { emit "final" {x:x;}; }
}
''', ["inner", "inner-recovery", "outer"], expected_events=[event("final", x=1)])
    yield "fatal-after-resume-not-caught", lambda: compare_runs('''
proc main() {
 transaction { pause "before-fatal"; let x:int=1/0; }
 recover(e) { emit "wrong" {}; }
}
''', ["before-fatal"], expected_failure=("RUNTIME", 5))
    yield "original-stack-preserved-across-handler-pause", lambda: compare_runs('''
proc leaf() { assert false; }
proc main() {
 transaction { leaf(); } recover(e) { pause code(e); }
 ship("missing",1);
}
''', ["ASSERT"], expected_failure=("DOMAIN", 4))
    yield "fatal-statement-budget-is-cumulative", lambda: compare_runs('''
proc main() {
 let i:int=0;
 while(i<10000) {
   set i=i+1;
   if(i==4000) { pause "budget"; }
 }
}
''', ["budget"], expected_failure=("RUNTIME", 5))
    yield "library-defaults-and-call-continuation", lambda: compare_runs('''
proc main() { let n:int=99; helper(label="same"); helper(2,label="same"); emit "caller" {n:n;}; }
''', ["same", "same"], library='''
proc helper(n:int=4,label:string="default") {
 let x:int=n+1; pause label; emit "helper" {x:x;}; return;
}
''', expected_events=[event("helper", x=5), event("helper", x=3), event("caller", n=99)])
    yield "held-record-mutated-after-pause-then-rolled-back", lambda: compare_runs('''
proc main() {
 reserve("h","east","gear",6);
 transaction {
   ship("h",2); pause "part-shipped"; release("h",3); assert false;
 } recover(e) { pause "restored"; emit "hold" {r:remaining("h"); a:available("east","gear");}; }
}
''', ["part-shipped", "restored"], expected_events=[event("hold", r=6, a=14)],
        expected_warehouses=INVENTORY["warehouses"],
        expected_holds={"h": {"warehouse": "east", "sku": "gear", "remaining": 6}})
    yield "two-nested-loops-distinguish-control-targets", lambda: compare_runs('''
proc main() {
 let i:int=0;
 while(i<2) {
   set i=i+1; let j:int=0;
   transaction {
     while(j<3) {
       set j=j+1; pause "loop";
       if(j==1) {continue;}
       if(j==2) {break;}
     }
     emit "pair" {i:i; j:j;};
   }
 }
}
''', ["loop"] * 4, expected_events=[event("pair", i=1, j=2), event("pair", i=2, j=2)])
    yield "resume-before-return-in-recovery", lambda: compare_runs('''
proc worker() {
 transaction {
   transaction { assert false; } recover(e) {
     receive("west","gear",2); pause code(e); return;
   }
 }
}
proc main() { worker(); emit "end" {}; }
''', ["ASSERT"], expected_events=[event("end")],
        expected_stats={"steps": 8, "committed": 1, "rolled_back": 1},
        expected_warehouses={"east": INVENTORY["warehouses"]["east"], "west": {"gear": 2}})
    for seed in range(12):
        rng = random.Random(18791 + seed)
        value, amount = rng.randrange(1, 100), rng.randrange(1, 8)
        abort = seed % 2 == 0
        source = f'''
proc main() {{
 let x:int={value};
 transaction {{
   transaction {{
     set x=x+{amount}; receive("west","gear",{amount});
     pause "same"; emit "inner" {{x:x;}};
   }}
   pause "same"; {"assert false;" if abort else 'emit "outer" {x:x;};'}
 }} recover(e) {{ pause "same"; emit "recovered" {{x:x;}}; }}
 emit "final" {{x:x;}};
}}
'''
        wh = copy.deepcopy(INVENTORY["warehouses"])
        if not abort:
            wh["west"]["gear"] = amount
        events = ([event("recovered", x=value), event("final", x=value)] if abort else
                  [event("inner", x=value+amount), event("outer", x=value+amount),
                   event("final", x=value+amount)])
        yield f"generated-durable-snapshot-{seed}", (
            lambda s=source, labels=["same"] * (3 if abort else 2), ev=events, state=wh:
            compare_runs(s, labels, expected_events=ev, expected_warehouses=state,
                         expected_holds={}))


def corrupted_case(mode: str):
    with tempfile.TemporaryDirectory(prefix="stockroom-corrupt-check-") as directory:
        root = Path(directory)
        source, incoming, lib = setup(root / "inputs",
                                     'proc main(){pause "label"; emit "done" {};}',
                                     'proc helper(){}' if mode.startswith("library") else None)
        output, saved, target = root / "out.json", root / "resume.json", root / "next.json"
        output.write_bytes(SENTINEL)
        target.write_bytes(b'{"prior":"checkpoint"}\n')
        status(invoke(source, incoming, output, library=lib, save=saved), 10)
        obj = json.loads(saved.read_text())
        if mode == "truncate":
            saved.write_bytes(saved.read_bytes()[:30])
        elif mode == "checksum":
            obj["label"] = "changed"
            saved.write_text(json.dumps(obj))
        elif mode == "duplicate-key":
            text = saved.read_text().lstrip()
            saved.write_text('{"version":1,' + text[1:])
        elif mode == "nonfinite":
            saved.write_text('{"version":NaN}')
        elif mode == "invalid-utf8":
            saved.write_bytes(b"\xff")
        elif mode in {"program-change", "input-change", "library-change"}:
            changed = source if mode.startswith("program") else incoming if mode.startswith("input") else lib
            changed.write_bytes(changed.read_bytes() + b"\n")
        elif mode == "program-invalid":
            source.write_text("@")
        elif mode == "input-invalid":
            incoming.write_text("{broken")
        elif mode == "library-omitted":
            lib = None
        else:
            if mode == "version":
                obj["version"] = 99
            elif mode == "boolean-version":
                obj["version"] = True
            elif mode == "boolean-count":
                obj["pause_count"] = True
            elif mode == "zero-count":
                obj["pause_count"] = 0
            elif mode == "state-empty":
                obj["state"] = {}
            elif mode == "state-list":
                obj["state"] = []
            elif mode == "format":
                obj["format"] = "other"
            elif mode == "label-type":
                obj["label"] = 3
            elif mode == "missing-field":
                del obj["label"]
            elif mode == "extra-field":
                obj["unexpected"] = "no"
            else:
                raise AssertionError(mode)
            saved.write_text(json.dumps(seal(obj)))
        before = saved.read_bytes()
        target_before = target.read_bytes()
        result = invoke(source, incoming, output, library=lib, resume=saved, save=target)
        diagnostic(result, "CHECKPOINT", 8)
        equal(output.read_bytes().hex(), SENTINEL.hex(), "corrupt resume changed output")
        equal(saved.read_bytes().hex(), before.hex(), "corrupt resume changed input checkpoint")
        equal(target.read_bytes().hex(), target_before.hex(), "corrupt resume changed target")


def publication_case(mode: str):
    with tempfile.TemporaryDirectory(prefix="stockroom-publish-check-") as directory:
        root = Path(directory)
        source, incoming, lib = setup(root / "inputs", 'proc main(){pause "one"; pause "two";}')
        output, saved = root / "result.json", root / "checkpoint.json"
        output.write_bytes(SENTINEL)
        if mode == "distinct-checkpoint-output":
            status(invoke(source, incoming, output, save=saved), 10)
            before = saved.read_bytes()
            target = root / "new.json"
            status(invoke(source, incoming, output, resume=saved, save=target), 10)
            equal(saved.read_bytes().hex(), before.hex(), "distinct resume input mutated")
            obj = checkpoint(target, source, incoming)
            equal(obj["pause_count"], 2, "next count")
            equal(obj["label"], "two", "next label")
            equal(output.read_bytes().hex(), SENTINEL.hex(), "pause output mutated")
        elif mode == "no-pause-does-not-create-checkpoint":
            source.write_text("proc main(){}")
            status(invoke(source, incoming, output, save=saved), 0)
            if saved.exists():
                raise AssertionError("Checkpoint created without a pause")
        elif mode == "no-pause-preserves-existing-checkpoint":
            source.write_text("proc main(){}")
            saved.write_bytes(b"existing-checkpoint")
            status(invoke(source, incoming, output, save=saved), 0)
            equal(saved.read_bytes().hex(), b"existing-checkpoint".hex(), "completion mutated checkpoint")
        elif mode == "missing-checkpoint-parent":
            diagnostic(invoke(source, incoming, output, save=root / "absent" / "cp.json"), "IO", 7)
            equal(output.read_bytes().hex(), SENTINEL.hex(), "failed checkpoint publication")
        elif mode == "fatal-before-pause-preserves-checkpoint":
            source.write_text('proc main(){let x:int=1/0; pause "never";}')
            saved.write_bytes(b"existing-checkpoint")
            diagnostic(invoke(source, incoming, output, save=saved), "RUNTIME", 5)
            equal(output.read_bytes().hex(), SENTINEL.hex(), "fatal changed result")
            equal(saved.read_bytes().hex(), b"existing-checkpoint".hex(), "fatal changed checkpoint")
        elif mode == "result-publication-failure-keeps-resume":
            status(invoke(source, incoming, output, save=saved), 10)
            status(invoke(source, incoming, output, resume=saved), 10)
            before = saved.read_bytes()
            diagnostic(invoke(source, incoming, root / "absent" / "result.json", resume=saved), "IO", 7)
            equal(saved.read_bytes().hex(), before.hex(), "failed result publication changed checkpoint")
        else:
            before_source, before_input = source.read_bytes(), incoming.read_bytes()
            if mode == "result-alias-source":
                diagnostic(invoke(source, incoming, source, save=saved), "IO", 7)
            elif mode == "checkpoint-alias-source":
                diagnostic(invoke(source, incoming, output, save=source), "IO", 7)
            elif mode == "checkpoint-alias-inventory":
                diagnostic(invoke(source, incoming, output, save=incoming), "IO", 7)
            elif mode == "result-alias-checkpoint":
                diagnostic(invoke(source, incoming, saved, save=saved), "IO", 7)
            elif mode == "result-alias-resume":
                status(invoke(source, incoming, output, save=saved), 10)
                before = saved.read_bytes()
                diagnostic(invoke(source, incoming, saved, resume=saved), "IO", 7)
                equal(saved.read_bytes().hex(), before.hex(), "alias corrupted resume")
            elif mode == "dotdot-alias":
                (source.parent / "subdir").mkdir()
                alias = source.parent / "subdir" / ".." / source.name
                diagnostic(invoke(source, incoming, alias, save=saved), "IO", 7)
            else:
                raise AssertionError(mode)
            if source.read_bytes() != before_source or incoming.read_bytes() != before_input:
                raise AssertionError("Alias check mutated inputs")


def static_pause_cases():
    for source in ['proc main(){pause 3;}', 'proc unused(){pause missing;} proc main(){}',
                   'proc main(){if(false){pause true;}}']:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program, incoming, _ = setup(root / "inputs", source)
            output = root / "result.json"
            output.write_bytes(SENTINEL)
            diagnostic(invoke(program, incoming, output, save=root / "cp.json"), "STATIC", 3)
            equal(output.read_bytes().hex(), SENTINEL.hex(), "static pause failure publication")


def incident_resume():
    saved = APP / "deliverable/checkpoint.json"
    source, incoming = APP / "incident/run.stock", APP / "incident/inventory.json"
    library = APP / "workflows/fulfill.stock"
    obj = checkpoint(saved, source, incoming, library)
    equal(obj["label"], "delta:reserved", "incident final checkpoint label")
    equal(obj["pause_count"], 7, "incident dynamic pause count")
    before = saved.read_bytes()
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "result.json"
        status(invoke(source, incoming, output, library=library, resume=saved), 0)
        equal(json.loads(output.read_text()), json.loads((APP / "deliverable/result.json").read_text()),
              "delivered checkpoint does not reproduce final result")
    equal(saved.read_bytes().hex(), before.hex(), "incident replay changed checkpoint")


def workflow_durable(seed: int):
    from test_semantics import workflow_reference
    rng = random.Random(42181 + seed)
    inventory = {"east": {"gear": 20, "seal": 10}, "west": {}}
    orders = []
    for index in range(8):
        orders.append((f"fresh{seed}_{index}", "gear", rng.randrange(1, 6),
                       rng.choice(["gear", "seal"]), rng.randrange(1, 6), "east", "west"))
    wh, holds, events = workflow_reference(inventory, orders)
    labels = [e["data"]["order"] + ":reserved" for e in events if e["name"] == "fulfilled"]
    source = "proc main() {" + "".join(
        "fulfill(" + ",".join(json.dumps(value) for value in order) + ");"
        for order in orders) + "}"
    compare_runs(source, labels, library=(APP / "workflows/fulfill.stock").read_text(),
                 expected_events=events, expected_warehouses=wh, expected_holds=holds)


def run_all():
    cases = list(continuation_cases())
    cases.extend((f"fresh-durable-workflow-{seed}", lambda s=seed: workflow_durable(s))
                 for seed in range(6))
    for mode in ("truncate", "checksum", "duplicate-key", "nonfinite", "invalid-utf8",
                 "program-change", "input-change", "program-invalid", "input-invalid",
                 "library-change", "library-omitted", "version", "boolean-version",
                 "boolean-count", "zero-count", "state-empty", "state-list", "format",
                 "label-type", "missing-field", "extra-field"):
        cases.append(("reject-" + mode, lambda m=mode: corrupted_case(m)))
    for mode in ("distinct-checkpoint-output", "no-pause-does-not-create-checkpoint",
                 "no-pause-preserves-existing-checkpoint", "missing-checkpoint-parent",
                 "fatal-before-pause-preserves-checkpoint", "result-publication-failure-keeps-resume",
                 "result-alias-source", "checkpoint-alias-source", "checkpoint-alias-inventory",
                 "result-alias-checkpoint", "result-alias-resume", "dotdot-alias"):
        cases.append((mode, lambda m=mode: publication_case(m)))
    cases += [("pause-static-types", static_pause_cases), ("incident-checkpoint-replay", incident_resume)]
    records = []
    for name, run in cases:
        try:
            run()
            records.append(dict(name=name, group="durability", passed=True))
        except (AssertionError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            records.append(dict(name=name, group="durability", passed=False,
                                detail=traceback.format_exc()))
    return records
