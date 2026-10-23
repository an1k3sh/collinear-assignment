"""Nineteen post-trial probes; not part of the frozen acceptance grader."""
import json
from pathlib import Path
import sys
import tempfile
import traceback

sys.path.insert(0, "/tests")
from durable_checks import (SENTINEL, compare_runs, diagnostic,
                            invoke, seal, setup, status)
from test_semantics import equal, event


def boundary():
    compare_runs('''
proc main() {
 let i:int=0;
 while(i<9998) { set i=i+1; let x:int=0; }
 pause "step-19999"; emit "last" {};
}
''', ["step-19999"], expected_events=[event("last")],
                 expected_stats={"steps": 20000, "committed": 0, "rolled_back": 0})


def unicode():
    compare_runs('''
proc main() {
 let word:string="caf\u00e9";
 transaction {
   emit "before" {word:word;}; pause word + "\U0001f69a";
   set word="changed"; assert false;
 } recover(e) { emit "apr\u00e8s" {word:word; length:len("\U0001f69a");}; }
}
''', ["caf\u00e9\U0001f69a"], expected_events=[event("apr\u00e8s", word="caf\u00e9", length=1)])


def scope_reuse():
    compare_runs('''
proc child() { let x:int=5; set x=6; pause "child"; }
proc main() {
 let x:int=1;
 transaction {
   if(true) { let x:int=10; set x=11; }
   if(true) { let x:int=20; set x=21; pause "sibling"; }
   child(); child(); assert false;
 } recover(e) { emit "restored" {x:x;}; }
}
''', ["sibling", "child", "child"], expected_events=[event("restored", x=1)])


def terminal_pause():
    compare_runs('proc main(){pause "last";}', ["last"], expected_events=[],
                 expected_stats={"steps": 1, "committed": 0, "rolled_back": 0})


def reordered():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source, incoming, _ = setup(root / "inputs", 'proc main(){pause "one"; emit "done" {};}')
        saved, output = root / "cp.json", root / "out.json"
        status(invoke(source, incoming, output, save=saved), 10)
        obj = json.loads(saved.read_text())
        obj = dict(reversed(list(obj.items())))
        saved.write_text(json.dumps(obj, indent=4, ensure_ascii=False))
        before = saved.read_bytes()
        status(invoke(source, incoming, output, resume=saved), 0)
        equal(saved.read_bytes().hex(), before.hex(), "snapshot preservation")
        equal(json.loads(output.read_text())["events"],
              [{"id": 1, "name": "done", "data": {}}], "valid reserialized checkpoint")


def marker_keys():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source, incoming, _ = setup(
            root / "inputs",
            'proc main(){pause "keys"; emit "count" {n:onhand("east","$fault");};}')
        incoming.write_text('{"warehouses":{"east":{"$fault":1,"$token":2}}}')
        saved, output = root / "cp.json", root / "out.json"
        status(invoke(source, incoming, output, save=saved), 10)
        status(invoke(source, incoming, output, resume=saved), 0)
        equal(json.loads(output.read_text())["warehouses"],
              {"east": {"$fault": 1, "$token": 2}}, "user data preserved")


def large_integer():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        digits = "1" * 5000
        source, incoming, _ = setup(root / "inputs",
                                    'proc main(){let n:int=' + digits +
                                    '; pause "big"; emit "big" {ok:n>0;};}')
        saved, output = root / "cp.json", root / "out.json"
        status(invoke(source, incoming, output, save=saved), 10)
        status(invoke(source, incoming, output, resume=saved), 0)
        equal(json.loads(output.read_text())["events"],
              [{"id": 1, "name": "big", "data": {"ok": True}}], "large int")


def missing_resume():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source, incoming, _ = setup(root / "inputs", 'proc main(){}')
        output = root / "out.json"
        output.write_bytes(SENTINEL)
        diagnostic(invoke(source, incoming, output, resume=root / "missing.json"), "IO", 7)
        equal(output.read_bytes().hex(), SENTINEL.hex(), "missing resume atomicity")


def float_version():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source, incoming, _ = setup(root / "inputs", 'proc main(){pause "one";}')
        saved, output = root / "cp.json", root / "out.json"
        status(invoke(source, incoming, output, save=saved), 10)
        obj = json.loads(saved.read_text())
        obj["version"] = 1.0
        saved.write_text(json.dumps(seal(obj)))
        diagnostic(invoke(source, incoming, output, resume=saved), "CHECKPOINT", 8)


def interaction_cases():
    yield "break-keeps-enclosing-transaction-tentative", lambda: compare_runs('''
proc main() {
 transaction {
   while(true) {
     transaction {
       receive("west","gear",2); pause "before-break"; break;
     }
   }
   pause "outer"; assert false;
 } recover(e) {emit "reverted" {};}
}
''', ["before-break", "outer"], expected_events=[event("reverted")],
        expected_warehouses={"east":{"gear":20,"seal":10},"west":{}},
        expected_holds={})
    yield "main-return-commits-all-exited-boundaries", lambda: compare_runs('''
proc main() {
 transaction {
   transaction { receive("west","gear",3); pause "return"; return; }
 }
 emit "unreachable" {};
}
''', ["return"], expected_events=[],
        expected_stats={"steps":5,"committed":2,"rolled_back":0},
        expected_warehouses={"east":{"gear":20,"seal":10},"west":{"gear":3}})
    yield "closed-hold-tombstone-after-two-restarts", lambda: compare_runs('''
proc main() {
 reserve("h","east","gear",2); ship("h",2); pause "closed";
 transaction { reserve("h","east","gear",1); }
 recover(e) { pause code(e); emit "caught" {reason:code(e);}; }
}
''', ["closed","DUPLICATE_HOLD"],
        expected_events=[event("caught",reason="DUPLICATE_HOLD")],
        expected_warehouses={"east":{"gear":18,"seal":10},"west":{}},
        expected_holds={"h":{"warehouse":"east","sku":"gear","remaining":0}})
    yield "recovery-binding-can-shadow-builtin-name", lambda: compare_runs('''
proc main() {
 let len:int=8;
 transaction { assert false; } recover(code) {
   pause code(code);
   emit "value" {length:len("abc"); outer:len; error:code(code);};
 }
}
''', ["ASSERT"], expected_events=[event("value",length=3,outer=8,error="ASSERT")])
    yield "new-zero-source-and-rollback-key-removal", lambda: compare_runs('''
proc main() {
 receive("west","new",2); move("west","east","new",2); pause "zero";
 transaction {
   receive("west","gone",1); reserve("removed","west","gone",1);
   pause "abort"; assert false;
 } recover(e) {}
 emit "levels" {west:onhand("west","new"); east:onhand("east","new");};
}
''', ["zero","abort"], expected_events=[event("levels",west=0,east=2)],
        expected_warehouses={"east":{"gear":20,"seal":10,"new":2},"west":{"new":0}},
        expected_holds={})
    yield "three-calls-and-handler-retain-correct-locals", lambda: compare_runs('''
proc third(x:int) {
 transaction { set x=99; pause "third"; assert false; }
 recover(e) {pause code(e); emit "third" {x:x;};}
}
proc second(x:int) { third(x+1); pause "second"; emit "second" {x:x;}; }
proc first(x:int) { second(x+1); pause "first"; emit "first" {x:x;}; }
proc main() { first(1); }
''', ["third","ASSERT","second","first"],
        expected_events=[event("third",x=3),event("second",x=2),event("first",x=1)])
    yield "error-propagates-through-unhandled-transactions-after-pause", lambda: compare_runs('''
proc leaf() {transaction {pause "leaf"; ship("absent",1);}}
proc middle() {transaction {leaf();}}
proc main() {middle();}
''', ["leaf"], expected_failure=("DOMAIN",4))
    yield "recovery-continue-commits-only-enclosing-exited-transaction", lambda: compare_runs('''
proc main() {
 let i:int=0;
 while(i<2) {
   set i=i+1;
   transaction {
     transaction {assert false;} recover(e) {
       receive("west","gear",1); pause "recover"; continue;
     }
   }
 }
 emit "end" {i:i;};
}
''', ["recover","recover"], expected_events=[event("end",i=2)],
        expected_warehouses={"east":{"gear":20,"seal":10},"west":{"gear":2}})
    yield "rollback-restores-string-and-bool-types", lambda: compare_runs('''
proc main() {
 let name:string="before"; let flag:bool=false;
 transaction {
   set name="after"; set flag=true;
   transaction {pause name; emit name {flag:flag;};}
   assert false;
 } recover(e) {pause name; emit name {flag:flag;};}
}
''', ["after","before"], expected_events=[event("before",flag=False)])
    yield "separate-sibling-recovery-scopes-reuse-error-name", lambda: compare_runs('''
proc main() {
 transaction { assert false; } recover(e) {
   pause code(e); emit code(e) {};
 }
 transaction { ship("missing",1); } recover(e) {
   pause code(e); emit code(e) {};
 }
}
''', ["ASSERT","HOLD"], expected_events=[event("ASSERT"),event("HOLD")])


def main():
    results = []
    for name, run in [("exact-20000-step-success", boundary),
                      ("unicode-label-and-data", unicode),
                      ("sibling-scope-and-call-frame-reuse", scope_reuse),
                      ("pause-is-final-statement", terminal_pause),
                      ("valid-checkpoint-key-order-and-whitespace", reordered),
                      ("user-sku-serialization-marker-collision", marker_keys),
                      ("5000-digit-integer-through-checkpoint", large_integer),
                      ("missing-resume-file", missing_resume),
                      ("float-checkpoint-version", float_version)] + list(interaction_cases()):
        try:
            run()
            results.append({"probe": name, "passed": True})
        except (AssertionError, OSError, ValueError, KeyError, TypeError):
            results.append({"probe": name, "passed": False, "detail": traceback.format_exc()})
    Path("/logs/verifier/supplemental-edge-audit.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
