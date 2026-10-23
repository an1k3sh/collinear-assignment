"""Black-box acceptance checks; no oracle imports or source matching."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import traceback
from typing import Any

APP = Path(os.environ.get("STOCKROOM_APP", "/app"))
LOG = Path(os.environ.get("STOCKROOM_LOG", "/logs/verifier"))
BASE = {"east": {"gear": 20, "seal": 10}, "west": {}}
CASES: list[dict[str, Any]] = []


def event(name: str, **data: Any) -> dict[str, Any]:
    return {"name": name, "data": data}


def equal(actual: Any, expected: Any, label: str) -> None:
    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def add(name: str, group: str, source: str, *, warehouses=None, holds=None,
        events=None, stats=None, error=None, code=None, library=None,
        raw_input=None, inventory=None, stack=None, location=None,
        missing_output_parent=False, missing_input=False, missing_source=False,
        output_absent=False):
    CASES.append(dict(name=name, group=group, source=source,
                      warehouses=copy.deepcopy(BASE if warehouses is None else warehouses),
                      holds={} if holds is None else holds,
                      events=[] if events is None else events, stats=stats,
                      error=error, code=code, library=library, raw_input=raw_input,
                      inventory={"warehouses": BASE} if inventory is None else inventory,
                      stack=stack, location=location,
                      missing_output_parent=missing_output_parent,
                      missing_input=missing_input,                       missing_source=missing_source, output_absent=output_absent))


def successful_structure(result: Any) -> None:
    if not isinstance(result, dict):
        raise AssertionError("Result must be an object")
    for key in ("warehouses", "holds", "stats"):
        if not isinstance(result.get(key), dict):
            raise AssertionError(f"Missing/invalid {key}")
    if not isinstance(result.get("events"), list):
        raise AssertionError("Missing event list")
    for warehouse, skus in result["warehouses"].items():
        for sku, value in skus.items():
            if type(value) is not int or value < 0:
                raise AssertionError("Invalid on-hand quantity")
            held = sum(h["remaining"] for h in result["holds"].values()
                       if h["warehouse"] == warehouse and h["sku"] == sku)
            if held > value:
                raise AssertionError("Reservation conservation violated")
    for hold in result["holds"].values():
        if (type(hold["remaining"]) is not int or hold["remaining"] < 0
                or hold["warehouse"] not in result["warehouses"]):
            raise AssertionError("Invalid hold")
    for index, item in enumerate(result["events"], 1):
        equal(item.get("id"), index, "event ID")
        if not isinstance(item.get("name"), str) or not isinstance(item.get("data"), dict):
            raise AssertionError("Invalid event")
        if any(type(v) not in (str, int, bool) for v in item["data"].values()):
            raise AssertionError("Non-scalar payload")
    for name in ("steps", "committed", "rolled_back"):
        if type(result["stats"].get(name)) is not int or result["stats"][name] < 0:
            raise AssertionError("Invalid execution stats")


def run_case(case: dict[str, Any]) -> None:
    with tempfile.TemporaryDirectory(prefix="stockroom-check-") as directory:
        root = Path(directory)
        source = root / "program.stock"
        incoming = root / "inventory.json"
        output = root / "result.json"
        if not case["missing_source"]:
            source.write_text(case["source"], encoding="utf-8")
        if not case["missing_input"]:
            incoming.write_text(case["raw_input"] if case["raw_input"] is not None
                                else json.dumps(case["inventory"]), encoding="utf-8")
        if case["missing_output_parent"]:
            output = root / "absent" / "result.json"
        command = [sys.executable, "-m", "stockroom", str(source),
                   "--inventory", str(incoming), "--out", str(output)]
        if case["library"] == "workflow":
            command += ["--library", str(APP / "workflows/fulfill.stock")]
        elif case["library"]:
            library = root / "library.stock"
            library.write_text(case["library"], encoding="utf-8")
            command += ["--library", str(library)]
        sentinel = b'{"previous":"committed output"}\n'
        if not case["missing_output_parent"] and not case["output_absent"]:
            output.write_bytes(sentinel)
        original = {p: p.read_bytes() for p in (source, incoming) if p.exists()}
        process = subprocess.run(command, cwd=APP, capture_output=True, text=True, timeout=12)
        for path, content in original.items():
            equal(path.read_bytes().hex(), content.hex(), "input mutation")
        if case["error"]:
            category, returncode = case["error"]
            equal(process.returncode, returncode, f"exit status; stderr={process.stderr}")
            if case["output_absent"]:
                if output.exists():
                    raise AssertionError("Failure created output")
            elif output.parent.exists():
                equal(output.read_bytes().hex(), sentinel.hex(), "failed publication")
            elif output.exists():
                raise AssertionError("Failure created output")
            lines = process.stderr.strip().splitlines()
            if len(lines) != 1:
                raise AssertionError(f"Expected one JSON diagnostic: {process.stderr!r}")
            diagnostic = json.loads(lines[0])
            equal(diagnostic.get("error"), category, "diagnostic category")
            if not isinstance(diagnostic.get("message"), str) or not diagnostic["message"]:
                raise AssertionError("Missing diagnostic message")
            if category in {"SYNTAX", "STATIC", "DOMAIN", "RUNTIME"}:
                if not isinstance(diagnostic.get("file"), str):
                    raise AssertionError("Missing source file")
                for key in ("line", "column"):
                    if type(diagnostic.get(key)) is not int or diagnostic[key] < 1:
                        raise AssertionError("Invalid source position")
            if category in {"DOMAIN", "RUNTIME"}:
                if not isinstance(diagnostic.get("stack"), list) or not diagnostic["stack"]:
                    raise AssertionError("Missing procedure stack")
            if case["code"]:
                equal(diagnostic.get("code"), case["code"], "domain code")
            if case["stack"]:
                equal(diagnostic.get("stack"), case["stack"], "procedure stack")
            if case["location"]:
                equal([diagnostic["line"], diagnostic["column"]], case["location"], "location")
            return
        equal(process.returncode, 0, f"exit status; stderr={process.stderr}")
        result = json.loads(output.read_text())
        successful_structure(result)
        equal(result["warehouses"], case["warehouses"], "warehouse state")
        equal(result["holds"], case["holds"], "hold state")
        expected = [dict(item, id=i) for i, item in enumerate(case["events"], 1)]
        equal(result["events"], expected, "committed events")
        if case["stats"] is not None:
            equal(result["stats"], case["stats"], "execution counters")


def language_cases() -> None:
    add("precedence-and-scalar-types", "language", '''
proc main() {
 emit "math" { n: 2 + 3 * 4; neg: -7 / 3; rem: -7 % 3;
               rem2: 7 % -3; nested: (2 + 3) * 4;
               ok: !false && 2 < 3 || false; text: "a" + "b";
               length: len("tab\\tquote\\""); distinct: true != false; };
}
''', events=[event("math", n=14, neg=-2, rem=-1, rem2=1, nested=20,
                  ok=True, text="ab", length=10, distinct=True)],
        stats={"steps": 1, "committed": 0, "rolled_back": 0})
    big = 10 ** 80 + 7
    add("integer-division-not-float", "language",
        f'proc main() {{ emit "big" {{ n: {big} / 3; r: {big} % 3; }}; }}',
        events=[event("big", n=big // 3, r=big % 3)])
    add("short-circuit", "language", '''
proc main() {
 assert true || remaining("missing") > 0;
 assert !(false && 1 / 0 == 3);
 emit "ok" {};
}
''', events=[event("ok")])
    add("defaults-named-forward-library", "language", '''
proc main() { later(2, label="route"); later(label="default", n=5); }
''', library='''
proc later(n: int, flag: bool = true, label: string = "x") {
 if (flag) { emit label { value: n; }; }
}
''', events=[event("route", value=2), event("default", value=5)])
    add("shadow-initializer-and-loop-lifetimes", "language", '''
proc main() {
 let x: int = 7;
 if (true) { let x: int = x + 1; set x = x + 1; emit "inner" { x: x; }; }
 let i: int = 0;
 while (i < 3) { let x: int = i; set i = i + 1; }
 emit "outer" { x: x; i: i; };
}
''', events=[event("inner", x=9), event("outer", x=7, i=3)])
    add("lexical-callee-isolation", "language", '''
proc child(value: int = 4) { set value = value + 1; emit "child" { v: value; }; }
proc main() { let value: int = 99; child(); emit "parent" { v: value; }; }
''', events=[event("child", v=5), event("parent", v=99)])
    add("strings-comments-braces", "language", '''
// lexer must not interpret braces/comments in quoted text
proc main() { emit "a//b{}" { text: "comma, colon: semi;"; }; }
''', events=[event("a//b{}", text="comma, colon: semi;")])
    invalid = [
        ("bool-not-int", 'let x: int = true;'),
        ("short-circuit-still-static", 'assert true || no_such_name;'),
        ("dead-branch-still-static", 'if (false) { set missing = 1; }'),
        ("unknown-procedure", 'missing();'),
        ("unknown-expression-function", 'let x: int = mystery(2);'),
        ("builtin-statement", 'onhand("east", "gear");'),
        ("error-escape", 'transaction { assert false; } recover (e) { emit "bad" { e: e; }; }'),
        ("error-reassignment", 'transaction { assert false; } recover (e) { set e = e; }'),
        ("duplicate-local", 'let x: int = 1; let x: int = 2;'),
        ("undefined-assignment", 'set x = 1;'),
        ("non-bool-if", 'if (1) {}'),
        ("break-without-loop", 'break;'),
        ("continue-without-loop", 'continue;'),
        ("duplicate-emit-key", 'emit "e" { x: 1; x: 2; };'),
        ("ordered-bools", 'assert true < false;'),
        ("mixed-equality", 'assert 1 == true;'),
        ("condition-assignment-type", 'let x: bool = true; set x = 2;'),
        ("builtin-named-arg", 'let x: int = len(value="abc");'),
        ("read-before-declare", 'let x: int = x + 1;'),
        ("recovery-name-outside", 'transaction {} recover(e) {} emit "e" { v: code(e); };'),
        ("recover-redeclare", 'transaction { assert false; } recover(e) { let e: int = 1; }'),
    ]
    for name, body in invalid:
        add(name, "validation", f"proc main() {{ {body} }}", error=("STATIC", 3))
    invalid_programs = [
        ("required-after-default", 'proc f(a:int=1,b:int) {} proc main() {}'),
        ("default-type", 'proc f(a:int=true) {} proc main() {}'),
        ("duplicate-param", 'proc f(a:int,a:int) {} proc main() {}'),
        ("param-local-redeclare", 'proc f(a:int) { let a:int=1; } proc main() {}'),
        ("duplicate-procedure", 'proc main() {} proc main() {}'),
        ("reserved-builtin-procedure", 'proc len() {} proc main() {}'),
        ("missing-main", 'proc helper() {}'),
        ("main-has-params", 'proc main(a:int=1) {}'),
        ("uncalled-body-static", 'proc f() { emit "x" {v: absent;}; } proc main() {}'),
        ("dynamic-scope-forbidden", 'proc f() {set x=2;} proc main(){let x:int=1;f();}'),
        ("indirect-dead-recursion", 'proc a(){if(false){b();}} proc b(){a();} proc main(){}'),
        ("direct-dead-recursion", 'proc a(){if(false){a();}} proc main(){}'),
        ("callee-cannot-break-caller", 'proc f(){break;} proc main(){while(true){f();break;}}'),
        ("proc-expression", 'proc f(){} proc main(){let x:int=f();}'),
        ("missing-argument", 'proc f(a:int){} proc main(){f();}'),
        ("extra-argument", 'proc f(){} proc main(){f(1);}'),
        ("unknown-named-argument", 'proc f(a:int=1){} proc main(){f(b=2);}'),
        ("duplicate-bound-argument", 'proc f(a:int){} proc main(){f(1,a=2);}'),
        ("positional-after-named", 'proc f(a:int,b:int){} proc main(){f(a=1,2);}'),
    ]
    for name, program in invalid_programs:
        add(name, "validation", program, error=("STATIC", 3))
    for name, program in [
        ("missing-semicolon", 'proc main(){let x:int=1}'),
        ("illegal-token", 'proc main(){ @ }'),
        ("invalid-json-escape", r'proc main(){emit "\q" {}; }'),
        ("unclosed-block", 'proc main(){'),
        ("keyword-identifier", 'proc main(){let return:int=2;}'),
    ]:
        add(name, "validation", program, error=("SYNTAX", 2))


def transaction_cases() -> None:
    add("nested-commit-outer-abort", "transactions", '''
proc main() {
 let value: int = 1;
 transaction {
   set value = 2;
   transaction {
     set value = 3; receive("east", "new", 4);
     reserve("gone", "east", "gear", 3); emit "gone" {};
   }
   assert false;
 } recover (e) { emit "restored" { v: value; why: code(e); }; }
 emit "last" {};
}
''', events=[event("restored", v=1, why="ASSERT"), event("last")],
        stats={"steps": 11, "committed": 1, "rolled_back": 1})
    add("recover-inside-outer-remains-tentative", "transactions", '''
proc main() {
 let value: int = 0;
 transaction {
   transaction { assert false; } recover (inner) {
     set value = 5; emit "lost-recovery" {}; receive("west", "gear", 4);
   }
   assert false;
 } recover (outer) { emit "outer" { v: value; c: code(outer); }; }
}
''', events=[event("outer", v=0, c="ASSERT")],
        stats={"steps": 9, "committed": 0, "rolled_back": 2})
    add("rollback-with-shadowed-binding", "transactions", '''
proc main() {
 let x: int = 1;
 transaction {
   set x = 2;
   if (true) { let x: int = 10;
     transaction { set x = 99; assert false; }
     recover(e) { emit "inner" { x: x; }; }
   }
   emit "before" { x: x; };
   assert false;
 } recover(e) { emit "after" { x: x; }; }
}
''', events=[event("after", x=1)])
    add("unhandled-inner-restores-before-outer-handler", "transactions", '''
proc main() {
 transaction {
   receive("east", "gear", 2);
   transaction { move("east", "west", "gear", 7); assert false; }
 } recover(e) { emit "free" { n: available("east", "gear"); why: code(e); }; }
}
''', events=[event("free", n=20, why="ASSERT")],
        stats={"steps": 6, "committed": 0, "rolled_back": 2})
    add("recovery-fails-to-outer-handler", "transactions", '''
proc main() {
 transaction {
   transaction { assert false; } recover(e) {
     receive("west", "gear", 8); assert false;
   }
 } recover(e) { emit "outer" { why: code(e); }; }
}
''', events=[event("outer", why="ASSERT")])
    add("return-commits-exited-transactions", "transactions", '''
proc worker() {
 transaction {
   transaction { receive("west", "gear", 4); emit "kept" {}; return; }
 }
 emit "unreachable" {};
}
proc main() { worker(); emit "end" {}; }
''', warehouses={"east": BASE["east"], "west": {"gear": 4}},
        events=[event("kept"), event("end")],
        stats={"steps": 7, "committed": 2, "rolled_back": 0})
    add("callee-return-does-not-commit-caller", "transactions", '''
proc child() { transaction { emit "child" {}; return; } }
proc main() {
 transaction { child(); assert false; } recover(e) { emit "caller" {}; }
}
''', events=[event("caller")],
        stats={"steps": 7, "committed": 1, "rolled_back": 1})
    add("loop-control-commits-and-stats", "transactions", '''
proc main() {
 let i: int = 0;
 while (i < 5) {
   set i = i + 1;
   transaction {
     receive("west", "gear", 1);
     if (i == 1) { continue; }
     if (i == 3) { break; }
     emit "middle" { i: i; };
   }
 }
 emit "end" { i: i; };
}
''', warehouses={"east": BASE["east"], "west": {"gear": 3}},
        events=[event("middle", i=2), event("end", i=3)],
        stats={"steps": 20, "committed": 3, "rolled_back": 0})
    add("loop-inside-transaction-break-does-not-exit-it", "transactions", '''
proc main() {
 transaction {
   while (true) { receive("west", "gear", 1); break; }
   assert false;
 } recover(e) { emit "rolled" {}; }
}
''', events=[event("rolled")],
        stats={"steps": 6, "committed": 0, "rolled_back": 1})
    add("recovery-scope-shadow-restores-binding", "transactions", '''
proc main() {
 let e: string = "outside";
 transaction { assert false; } recover(e) {
   if (true) { let e: string = "shadow"; emit e {}; }
   emit code(e) {};
 }
 emit e {};
}
''', events=[event("shadow"), event("ASSERT"), event("outside")])
    for seed in range(12):
        rng = random.Random(1913 + seed)
        start, inner, outer = [rng.randrange(1, 50) for _ in range(3)]
        abort_outer = seed % 2 == 0
        program = f'''
proc main() {{
 let x: int = {start};
 transaction {{
   set x = {outer};
   transaction {{
     set x = {inner}; receive("west", "gear", {inner});
     emit "inner" {{ x: x; }};
   }}
   {"assert false;" if abort_outer else 'emit "outer" {x:x;};'}
 }} recover(e) {{ emit "recovered" {{x:x;}}; }}
 emit "final" {{x:x;}};
}}
'''
        wh = copy.deepcopy(BASE)
        if abort_outer:
            events = [event("recovered", x=start), event("final", x=start)]
        else:
            wh["west"]["gear"] = inner
            events = [event("inner", x=inner), event("outer", x=inner), event("final", x=inner)]
        add(f"snapshot-metamorphic-{seed}", "transactions", program, warehouses=wh, events=events)


def inventory_cases() -> None:
    add("hold-conservation-and-tombstones", "inventory", '''
proc main() {
 reserve("a","east","gear",8); release("a",3); ship("a",2);
 move("east","west","gear",10);
 emit "levels" { free:available("east","gear"); hand:onhand("east","gear"); held:remaining("a"); };
 release("a",3);
 transaction { reserve("a","east","gear",1); } recover(e) { emit code(e) {}; }
}
''', warehouses={"east": {"gear": 8, "seal": 10}, "west": {"gear": 10}},
        holds={"a": {"warehouse": "east", "sku": "gear", "remaining": 0}},
        events=[event("levels", free=5, hand=8, held=3), event("DUPLICATE_HOLD")])
    add("reads-do-not-materialize-zero", "inventory", '''
proc main() {
 assert onhand("west","new")==0;
 assert available("west","new")==0;
 transaction { move("west","east","new",1); } recover(e) { emit code(e) {}; }
}
''', events=[event("SHORTAGE")])
    add("rollback-hold-records-not-just-map", "inventory", '''
proc main() {
 reserve("h","east","gear",6);
 transaction { ship("h",2); release("h",3); assert false; } recover(e) {}
 emit "h" { n:remaining("h"); free:available("east","gear"); };
}
''', holds={"h": {"warehouse": "east", "sku": "gear", "remaining": 6}},
        events=[event("h", n=6, free=14)])
    operations = [
        ('move("east","west","gear",18);', "SHORTAGE"),
        ('reserve("other","east","gear",18);', "SHORTAGE"),
        ('move("east","missing","gear",1);', "WAREHOUSE"),
        ('move("east","east","gear",1);', "SAME_WAREHOUSE"),
        ('receive("east","gear",0);', "QUANTITY"),
        ('reserve("bad","east","gear",-1);', "QUANTITY"),
        ('release("live",0);', "QUANTITY"),
        ('ship("live",4);', "SHORTAGE"),
        ('release("live",4);', "SHORTAGE"),
        ('ship("missing",1);', "HOLD"),
        ('reserve("live","east","gear",1);', "DUPLICATE_HOLD"),
        ('receive("east","",1);', "NAME"),
        ('reserve("","east","gear",1);', "NAME"),
        ('release("",1);', "NAME"),
    ]
    for index, (operation, code) in enumerate(operations):
        add(f"operation-atomicity-{index}", "inventory", f'''
proc main() {{
 reserve("live","east","gear",3);
 transaction {{ {operation} }} recover(e) {{ emit code(e) {{}}; }}
}}
''', holds={"live": {"warehouse": "east", "sku": "gear", "remaining": 3}},
            events=[event(code)])
    add("left-to-right-expression-failure", "inventory", '''
proc main() { move("east", "west", "gear", onhand("missing","gear") + remaining("second")); }
''', error=("DOMAIN", 4), code="WAREHOUSE", stack=["main"])
    add("left-to-right-procedure-arguments", "inventory", '''
proc take(a:int,b:int) {}
proc main() { take(onhand("missing","gear"),remaining("second")); }
''', error=("DOMAIN", 4), code="WAREHOUSE", stack=["main"])


def failure_cases() -> None:
    add("fatal-not-caught-by-domain-handler", "publication", '''
proc main() {
 transaction { receive("west","gear",1); let x:int=1/0; }
 recover(e) { emit "must-not-run" {}; }
}
''', error=("RUNTIME", 5), stack=["main"])
    add("step-limit-not-caught", "publication", '''
proc main() {
 transaction { while(true) { let x:int=1; } }
 recover(e) { emit "must-not-run" {}; }
}
''', error=("RUNTIME", 5), stack=["main"])
    add("unhandled-domain-stack-location", "publication",
        'proc leaf() {\n  assert false;\n}\n'
        'proc middle() {transaction {leaf();}}\nproc main(){middle();}',
        error=("DOMAIN", 4), code="ASSERT", stack=["main", "middle", "leaf"],
        location=[2, 3])
    add("unreachable-static-before-runtime", "publication",
        'proc main(){receive("east","gear",1); let x:int=1/0;}'
        'proc unused(){set x=1;}', error=("STATIC", 3))
    invalid_inputs = [
        '{"warehouses":{"east":{"gear":true}}}',
        '{"warehouses":{"east":{"gear":-1}}}',
        '{"warehouses":{"east":{"gear":1.5}}}',
        '{"warehouses":{"east":{"gear":1,"gear":2}}}',
        '{"warehouses":{"east":[]} }',
        '{"warehouses":{"":{"gear":1}}}',
        '{"warehouses":{"east":{"":1}}}',
        '{"warehouses":{},"extra":1}',
        '{"warehouses":{"east":{"gear":NaN}}}',
        '{"warehouses":null}',
        '[]',
        '{broken',
    ]
    for index, incoming in enumerate(invalid_inputs):
        add(f"inventory-validation-{index}", "publication", "proc main() {}",
            raw_input=incoming, error=("INPUT", 6))
    add("publication-parent-must-exist", "publication", "proc main() {}",
        missing_output_parent=True, error=("IO", 7))
    add("missing-input", "publication", "proc main() {}",
        missing_input=True, error=("IO", 7))
    add("missing-program", "publication", "proc main() {}",
        missing_source=True, error=("IO", 7))
    add("absent-output-domain", "publication", "proc main(){assert false;}",
        output_absent=True, error=("DOMAIN", 4), code="ASSERT")
    add("absent-output-static", "publication", "proc main(){set absent=2;}",
        output_absent=True, error=("STATIC", 3))
    add("absent-output-runtime", "publication", "proc main(){let x:int=1/0;}",
        output_absent=True, error=("RUNTIME", 5))


def workflow_reference(warehouses, orders):
    wh, holds, events = copy.deepcopy(warehouses), {}, []
    for order, a, qa, b, qb, preferred, fallback in orders:
        requirements = {a: qa}
        requirements[b] = requirements.get(b, 0) + qb
        chosen = next((w for w in (preferred, fallback)
                       if all(wh[w].get(sku, 0) >= qty for sku, qty in requirements.items())), None)
        if chosen is None:
            events.append(event("deferred", order=order, reason="SHORTAGE"))
            continue
        for suffix, sku, qty in [(".a", a, qa), (".b", b, qb)]:
            wh[chosen][sku] -= qty
            holds[order + suffix] = {"warehouse": chosen, "sku": sku, "remaining": 0}
        events.append(event("fulfilled", order=order, warehouse=chosen, units=qa + qb))
    return wh, holds, events


def workflow_cases() -> None:
    for seed in range(16):
        rng = random.Random(64017 + seed)
        wh = {w: {sku: rng.randrange(5, 35) for sku in ("gear", "seal", "bolt")}
              for w in ("north", "south")}
        orders = []
        for index in range(12):
            a, b = rng.choice(["gear", "seal", "bolt"]), rng.choice(["gear", "seal", "bolt"])
            preferred, fallback = ("north", "south") if rng.randrange(2) else ("south", "north")
            orders.append((f"order{seed}_{index}", a, rng.randrange(1, 9), b,
                           rng.randrange(1, 9), preferred, fallback))
        expected_wh, holds, events = workflow_reference(wh, orders)
        calls = ["fulfill(" + ",".join(json.dumps(v) for v in order) + ");" for order in orders]
        add(f"fresh-bundle-stream-{seed}", "workflow",
            "proc main() { let order:string=\"caller-local\";" + "".join(calls)
            + 'emit order {};}', library="workflow", inventory={"warehouses": wh},
            warehouses=expected_wh, holds=holds, events=events + [event("caller-local")])
    add("workflow-enclosing-rollback", "workflow", '''
proc main() {
 transaction { fulfill("x","gear",2,"seal",2,"east","west"); assert false; }
 recover(e) { emit "reverted" {}; }
 fulfill("x","gear",2,"seal",2,"east","west");
}
''', library="workflow", warehouses={"east": {"gear": 18, "seal": 8}, "west": {}},
        holds={f"x.{suffix}": {"warehouse": "east", "sku": sku, "remaining": 0}
               for suffix, sku in [("a", "gear"), ("b", "seal")]},
        events=[event("reverted"), event("fulfilled", order="x", warehouse="east", units=4)])
    add("workflow-must-respect-existing-holds", "workflow", '''
proc main() {
 reserve("safety","east","gear",18);
 receive("west","gear",5); receive("west","seal",5);
 fulfill("x","gear",3,"seal",3,"east","west");
}
''', library="workflow",
        warehouses={"east": BASE["east"], "west": {"gear": 2, "seal": 2}},
        holds={"safety": {"warehouse": "east", "sku": "gear", "remaining": 18},
               "x.a": {"warehouse": "west", "sku": "gear", "remaining": 0},
               "x.b": {"warehouse": "west", "sku": "seal", "remaining": 0}},
        events=[event("fulfilled", order="x", warehouse="west", units=6)])


def incident_check() -> None:
    path = APP / "deliverable/result.json"
    actual = json.loads(path.read_text())
    successful_structure(actual)
    equal(actual["warehouses"], {"east": {"gear": 3, "seal": 0},
                                "west": {"gear": 3, "seal": 6},
                                "overflow": {"gear": 0, "seal": 0}}, "incident inventory")
    expected_holds = {"safety": {"warehouse": "east", "sku": "gear", "remaining": 0}}
    for order, warehouse in [("alpha", "west"), ("beta", "east"), ("delta", "east")]:
        for suffix, sku in [("a", "gear"), ("b", "seal")]:
            expected_holds[order + "." + suffix] = dict(warehouse=warehouse, sku=sku, remaining=0)
    equal(actual["holds"], expected_holds, "incident holds")
    events = [
        event("rehearsal_reverted", attempts=0, reason="ASSERT"),
        event("fulfilled", order="alpha", warehouse="west", units=12),
        event("fulfilled", order="beta", warehouse="east", units=8),
        event("deferred", order="gamma", reason="SHORTAGE"),
        event("fulfilled", order="delta", warehouse="east", units=6),
        event("closing", east_gear=3, west_gear=3),
    ]
    equal(actual["events"], [dict(e, id=i) for i, e in enumerate(events, 1)], "incident events")
    handoff = APP / "deliverable/HANDOFF.md"
    if not handoff.is_file() or not handoff.read_text(encoding="utf-8").strip():
        raise AssertionError("Missing handoff (prose content is reviewed manually, not string-graded)")


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    language_cases()
    transaction_cases()
    inventory_cases()
    failure_cases()
    workflow_cases()
    records = []
    for case in CASES:
        try:
            run_case(case)
            records.append(dict(name=case["name"], group=case["group"], passed=True))
        except (AssertionError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            records.append(dict(name=case["name"], group=case["group"], passed=False,
                                detail=traceback.format_exc()))
    try:
        incident_check()
        records.append(dict(name="incident-deliverable", group="deliverable", passed=True))
    except (AssertionError, OSError, ValueError, KeyError, TypeError):
        records.append(dict(name="incident-deliverable", group="deliverable", passed=False,
                            detail=traceback.format_exc()))
    from durable_checks import run_all
    records.extend(run_all())
    from carrier_checks import run_all as carrier_checks
    records.extend(carrier_checks())
    groups = {}
    for group in sorted({item["group"] for item in records}):
        rows = [item for item in records if item["group"] == group]
        groups[group] = sum(item["passed"] for item in rows) / len(rows)
    rewards = {
        "overall": float(all(item["passed"] for item in records)),
        "functional_correctness": (groups["language"] + groups["inventory"] + groups["workflow"]) / 3,
        "constraint_satisfaction": (groups["validation"] + groups["publication"]) / 2,
        "robustness": (groups["transactions"] + groups["durability"]) / 2,
        "durability": groups["durability"],
        "external_consistency": groups["carrier"],
        "artifact_quality": groups["deliverable"],
    }
    (LOG / "checks.json").write_text(json.dumps({"groups": groups, "checks": records}, indent=2))
    (LOG / "reward.json").write_text(json.dumps(rewards, indent=2) + "\n")
    print(json.dumps({"rewards": rewards, "groups": groups,
                      "passed": sum(r["passed"] for r in records), "total": len(records)}))
    for record in records:
        if not record["passed"]:
            print(record["name"] + ": " + record["detail"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
