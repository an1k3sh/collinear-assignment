"""Independent behavioral verification. No candidate compiler imports."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import traceback

import reference as ref
from schema import validate_case

ERRORS = (AssertionError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error,
          subprocess.SubprocessError, OSError)
CORRECTNESS = (*ref.MODES, "extended", "comparison", "composition", "injection", "bindings")
DIVERSITY = ("coverage", "data", "structure", "occupancy", "grammar", "sensitivity", "live")
GATES = ("build", "determinism_replay", "libfuzzer",
         "diversity.data", "diversity.structure", "diversity.occupancy",
         "diversity.sensitivity", "diversity.live")


def score(details, metrics):
    measured = [metrics[k] for k in ("random", "mutations", "live") if k in metrics]
    attempted = sum(m["attempted"] for m in measured)
    validity = sum(m["executable"] for m in measured) / attempted if attempted else 0.0
    semantic = sum(m["semantic"] for m in measured) / attempted if attempted else 0.0
    correctness = sum(details.get("correctness."+k, False) for k in CORRECTNESS) / len(CORRECTNESS)
    diversity = sum(details.get("diversity."+k, False) for k in DIVERSITY) / len(DIVERSITY)
    gate = (all(details.get(k) for k in GATES) and
            correctness == 1 and validity == 1 and semantic == 1)
    return {"overall": diversity if gate else 0.0, "input_validity_rate": validity,
            "semantic_validity_rate": semantic, "oracle_correctness": correctness,
            "diversity": diversity}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def topology(value):
    if isinstance(value, list):
        if value and value[0] == "col":
            return ["col"]
        if value and value[0] == "lit":
            return ["lit", type(value[1]).__name__]
        return [topology(v) for v in value]
    if isinstance(value, dict):
        return {k: topology(v) for k, v in value.items() if k != "tables"}
    return value


def nodes(value):
    if isinstance(value, list):
        if value and isinstance(value[0], str):
            yield value
        for child in value:
            yield from nodes(child)


def depth(value):
    if not isinstance(value, list):
        return 0
    return 1 + max((depth(v) for v in value), default=0)


def readonly(action, _a, _b, _database, _trigger):
    return sqlite3.SQLITE_OK if action in (
        sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE) else sqlite3.SQLITE_DENY


def query(db, q):
    assert set(q) == {"sql", "params"}
    assert isinstance(q["sql"], str) and isinstance(q["params"], list)
    return [list(row) for row in db.execute(q["sql"], q["params"])]


def verify_answer(answer, changed=True):
    c = answer["case"]
    validate_case(c)
    plan = answer["plan"]
    assert set(plan) == {"base", "parts"} and len(plan["parts"]) == 3
    with closing(ref.connect(c)) as db:
        db.set_authorizer(readonly)
        actual = [query(db, q) for q in [plan["base"], *plan["parts"]]]
        expected = [ref.reference_rows(db, c)] + [
            ref.reference_rows(db, c, i, stats=True) for i in range(3)]
        assert all(ref.bag(a) == ref.bag(b) for a, b in zip(actual, expected)), "query meaning"
        result = answer["result"]
        assert result["calls"] == 4
        assert result["equivalent"] is True
        assert ref.bag(result["base"]) == ref.bag(expected[0]), "reported baseline"
        assert ref.bag(result["combined"]) == ref.bag(expected[0]), "composition"
    if changed:
        alternate = copy.deepcopy(c)
        alternate["tables"] = {
            "t": [[3, 0, -9, "new'\0"], [3, 0, 4, "new'\0"], [None, 1, None, None],
                  [-7, None, 12, "x"], [1, 2, 0, ""]],
            "u": [[1, 0, 2, "u"], [1, 0, None, "u"], [8, 1, -3, None], [2, 5, 4, "z"]]}
        with closing(ref.connect(alternate)) as db:
            db.set_authorizer(readonly)
            actual = [query(db, q) for q in [plan["base"], *plan["parts"]]]
            expected = [ref.reference_rows(db, alternate)] + [
                ref.reference_rows(db, alternate, i, stats=True) for i in range(3)]
            assert all(ref.bag(a) == ref.bag(b) for a, b in zip(actual, expected)), "changed data"


class Verifier:
    def __init__(self, app, log):
        self.app, self.log = Path(app), Path(log)
        self.log.mkdir(parents=True, exist_ok=True)
        self.cli = self.log / "build" / "tlp_cli"
        self.fuzz = self.log / "build" / "tlp_fuzz"
        self.details = {}
        self.metrics = {}
        self.failures = []

    def command(self, argv, **kwargs):
        return subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                              timeout=kwargs.pop("timeout", 120), **kwargs)

    def request(self, requests):
        run = self.command([self.cli], input="".join(canonical(r)+"\n" for r in requests))
        if run.returncode:
            raise AssertionError(f"CLI exit {run.returncode}: {run.stderr[-4000:]}")
        answers = [json.loads(line) for line in run.stdout.splitlines()]
        assert len(answers) == len(requests), "missing CLI outputs"
        return answers

    def test(self, name, operation):
        try:
            operation()
            self.details[name] = True
        except ERRORS:
            self.details[name] = False
            self.failures.append({"test": name, "error": traceback.format_exc()})
        print(name, "PASS" if self.details[name] else "FAIL", flush=True)

    def build(self):
        manifest = json.loads((Path(__file__).parent / "protected.json").read_text())
        for path, expected in manifest.items():
            assert hashlib.sha256((self.app / path).read_bytes()).hexdigest() == expected, path
        for args in (["cmake", "-S", self.app, "-B", self.cli.parent, "-G", "Ninja",
                      "-DCMAKE_CXX_COMPILER=clang++-16"],
                     ["cmake", "--build", self.cli.parent, "-j2"]):
            result = self.command(args, timeout=180)
            with (self.log / "build.log").open("a") as output:
                output.write(result.stdout + result.stderr)
            assert result.returncode == 0, result.stderr[-6000:]

    def fixtures(self, mode):
        cases = [c for c in ref.fixtures() if c["mode"] == mode]
        if mode == "extended":
            cases = [c for c in ref.fixtures() if c["mode"] == "rows" and c["where"] is not None]
        assert cases
        answers = self.request([{"op": "case", "case": c} for c in cases])
        for c, answer in zip(cases, answers):
            assert answer["case"] == c
            verify_answer(answer)

    def comparison(self):
        pairs = [([[1]], [[1.0]], False), ([[1]], [["1"]], False),
                 ([[None]], [[0]], False), ([[1], [1]], [[1]], False),
                 ([[1], [2]], [[2], [1]], True), ([[1, 2]], [[2, 1]], False),
                 ([[-0.0]], [[0.0]], True)]
        answers = self.request([{"op": "equal", "a": a, "b": b} for a, b, _ in pairs])
        for (_, _, expected), answer in zip(pairs, answers):
            assert answer == {"equal": expected}

    def composition(self):
        cases = []
        for mode, parts, expected in [
            ("rows", [[[1], [1]], [[2]], [[None]]], [[1], [1], [2], [None]]),
            ("distinct", [[[1], [1]], [[1], [2]], [[None], [None]]], [[1], [2], [None]]),
            ("group", [[[1]], [[1], [2]], [[None]]], [[1], [2], [None]]),
            ("having", [[[7]], [[7]], [[None]]], [[7], [7], [None]]),
            ("count", [[[2]], [[0]], [[3]]], [[5]]),
            ("sum", [[[None, 0]], [[None, 0]], [[None, 0]]], [[None]]),
            ("sum", [[[4, 1]], [[-4, 1]], [[None, 0]]], [[0]]),
            ("avg", [[[12, 3]], [[10, 1]], [[None, 0]]], [[5.5]]),
            ("min", [[[None]], [[2]], [[-3]]], [[-3]]),
            ("max", [[[None]], [[None]], [[None]]], [[None]]),
        ]:
            c = dict(ref.example(), mode=mode, group_by=[], select=[],
                     value=["col", "t", "v"])
            if mode in ("rows", "distinct"):
                c.update(select=[["col", "t", "v"]], value=None)
            if mode == "group":
                c.update(group_by=[["col", "t", "k"]], select=[["col", "t", "k"]], value=None)
            if mode == "having":
                aggregate = ["agg", "sum", ["col", "t", "v"]]
                c.update(select=[aggregate], value=None,
                         predicate=["gt", aggregate, ["lit", 0]])
            validate_case(c)
            cases.append(({"op": "compose", "case": c, "parts": parts}, expected))
        c = dict(ref.example(), mode="avg", group_by=[["col", "t", "k"]],
                 select=[], value=["col", "t", "v"])
        cases.append(({"op": "compose", "case": c, "parts":
                       [[[1, 10, 2]], [[2, 9, 3]], [[1, None, 0]]]}, [[1, 5.0], [2, 3.0]]))
        for answer, (_, expected) in zip(self.request([r for r, _ in cases]), cases):
            assert ref.bag(answer["rows"]) == ref.bag(expected)

    def injection(self):
        c = ref.example()
        for call in (1, 2, 3, 4):
            answer = self.request([{"op": "inject", "case": c, "call": call,
                                    "rows": [[987654321]]}])[0]
            assert answer["result"]["calls"] == 4
            assert answer["result"]["equivalent"] is False
        for mode in ref.MODES:
            sample = next(c for c in ref.fixtures() if c["mode"] == mode)
            width = len(sample["select"]) if mode in ("rows", "distinct", "group", "having") \
                else len(sample["group_by"]) + 1
            answer = self.request([{"op": "inject", "case": sample, "call": 1,
                                    "rows": [[987654321]*width]}])[0]
            assert answer["result"]["calls"] == 4
            assert answer["result"]["equivalent"] is False, mode
        result = self.command([self.cli], input=canonical({"op": "error", "case": c})+"\n")
        assert result.returncode == 2 and "injected execution error" in result.stderr

    def binding(self):
        c = ref.example()
        sentinel = "quote'\0;--"
        c["select"] = [["lit", sentinel]]
        answer = self.request([{"op": "case", "case": c}])[0]
        verify_answer(answer)
        for q in [answer["plan"]["base"], *answer["plan"]["parts"]]:
            assert sentinel in q["params"], "literal must be bound"

    def measured_inputs(self, blobs, label):
        requests = [{"op": "inspect", "hex": b.hex()} for b in blobs]
        run = self.command([self.cli], input="".join(canonical(r)+"\n" for r in requests),
                           timeout=150)
        if run.returncode:
            self.failures.append({"test": label, "error": run.stderr[-4000:],
                                  "exit_code": run.returncode})
        answers = [json.loads(line) for line in run.stdout.splitlines()]
        assert len(answers) <= len(blobs), "extra outputs"
        schema_ok = executable = semantic = 0
        errors = []
        for index, answer in enumerate(answers):
            try:
                validate_case(answer["case"])
                schema_ok += 1
                with closing(ref.connect(answer["case"])) as db:
                    db.set_authorizer(readonly)
                    plan = answer["plan"]
                    assert len(plan["parts"]) == 3
                    for q in [plan["base"], *plan["parts"]]:
                        query(db, q)
                executable += 1
                verify_answer(answer)
                semantic += 1
            except ERRORS:
                if len(errors) < 10:
                    errors.append({"input": index, "error": traceback.format_exc()})
        counts = {"attempted": len(blobs), "emitted": len(answers), "schema_valid": schema_ok,
                  "executable": executable, "semantic": semantic, "errors": errors}
        self.metrics[label] = counts
        (self.log / (label + "-counts.json")).write_text(json.dumps(counts, indent=2)+"\n")
        return answers

    def diversity(self, cases):
        modes = Counter(c["mode"] for c in cases)
        sources = Counter(c["source"] for c in cases)
        shapes = {canonical(ref.fingerprint(c)) for c in cases}
        topologies = {canonical(topology(c)) for c in cases}
        per_mode = {mode: len({canonical(topology(c)) for c in cases if c["mode"] == mode})
                    for mode in ref.MODES}
        counts = {
            "modes": dict(modes), "sources": dict(sources), "structural": len(shapes),
            "topologies": len(topologies), "topologies_per_mode": per_mode,
            "unique_cases": len({canonical(c) for c in cases}),
            "unique_databases": len({canonical(c["tables"]) for c in cases}),
            "where": sum(c["where"] is not None for c in cases),
            "grouped_aggregates": sum(c["mode"] in ref.AGGREGATES and bool(c["group_by"])
                                      for c in cases),
            "three_way": 0, "nonempty": 0, "group_overlap": 0,
            "having_duplicates": 0, "empty_row_stage": 0, "all_null": 0,
        }
        ops, columns, aggregates = set(), set(), set()
        nested, star, count_value = 0, 0, 0
        for c in cases:
            nested += depth(c["predicate"]) >= 3
            star += c["mode"] == "count" and c["value"] is None
            count_value += c["mode"] == "count" and c["value"] is not None
            for field in ("predicate", "where", "select", "value", "group_by"):
                for node in nodes(c[field]):
                    ops.add(node[0])
                    if node[0] == "col": columns.add((node[1], node[2]))
                    if node[0] == "agg": aggregates.add(node[1])
            with closing(ref.connect(c)) as db:
                sizes = ref.partition_sizes(db, c)
                baseline = ref.reference_rows(db, c)
                counts["three_way"] += all(sizes)
                counts["nonempty"] += bool(baseline)
                counts["empty_row_stage"] += c["mode"] != "having" and sum(sizes) == 0
                counts["all_null"] += (c["mode"] in ("sum", "avg", "min", "max") and
                                       sum(sizes) > 0 and bool(baseline) and
                                       all(row[-1] is None for row in baseline))
                if c["mode"] == "group":
                    parts = [ref.bag(ref.reference_rows(db, c, i)) for i in range(3)]
                    counts["group_overlap"] += any(parts[i].keys() & parts[j].keys()
                                                    for i, j in ((0, 1), (0, 2), (1, 2)))
                if c["mode"] == "having":
                    counts["having_duplicates"] += len(baseline) > len(ref.bag(baseline))
        counts.update(operators=sorted(ops), columns=sorted(columns),
                      aggregates=sorted(aggregates), nested=nested, count_star=star,
                      count_expression=count_value)
        self.metrics["diversity"] = counts
        checks = {
            "diversity.coverage": (all(modes[m] >= 40 for m in ref.MODES) and
                                  all(sources[s] >= 100 for s in ("single", "inner", "left")) and
                                  counts["where"] >= 200 and counts["grouped_aggregates"] >= 100),
            "diversity.data": counts["unique_cases"] >= 950 and counts["unique_databases"] >= 900,
            "diversity.structure": len(shapes) >= 256 and len(topologies) >= 128 and
                                   all(n >= 8 for n in per_mode.values()),
            "diversity.occupancy": counts["three_way"] >= 50 and counts["nonempty"] >= 500 and
                                   all(counts[k] >= 6 for k in ("group_overlap", "having_duplicates",
                                                                "empty_row_stage", "all_null")),
            "diversity.grammar": (
                {"col", "lit", "add", "sub", "eq", "ne", "lt", "le", "gt", "ge", "and", "or",
                 "not", "isnull", "agg"} <= ops and
                {"t", "u"} <= {t for t, _ in columns} and
                {"id", "k", "v", "tag"} <= {name for _, name in columns} and
                set(ref.AGGREGATES) <= aggregates and nested >= 100 and star > 0 and count_value > 0)
        }
        self.details.update(checks)

    def sensitivity(self):
        rng = random.Random(473091)
        blobs = []
        for _ in range(64):
            base = rng.randbytes(128)
            blobs.append(base)
            for quarter in range(4):
                start = 32 * quarter
                blobs.append(base[:start] + rng.randbytes(32) + base[start+32:])
        answers = self.measured_inputs(blobs, "mutations")
        assert len(answers) == 320
        changed, structural = [0]*4, [0]*4
        for offset in range(0, 320, 5):
            base = answers[offset]["case"]
            for quarter in range(4):
                other = answers[offset+quarter+1]["case"]
                changed[quarter] += base != other
                structural[quarter] += topology(base) != topology(other)
        self.metrics["sensitivity"] = {"case_changes": changed, "topology_changes": structural}
        assert min(changed) >= 32 and sum(n >= 16 for n in structural) >= 2

    def determinism(self):
        inputs = [b"", b"\0", b"\xff"*512, bytes(range(256)), b"x"*128, b"\x80"]
        requests = [{"op": "inspect", "hex": b.hex()} for b in inputs]
        a = self.request(requests + requests)
        b = self.request(requests)
        assert a[:len(inputs)] == a[len(inputs):] == b
        for i, blob in enumerate(inputs):
            path = self.log / f"replay-{i}.bin"
            path.write_bytes(blob)
            result = self.command([self.cli, "replay", path])
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout) == {"replayed": True}
        for answer in a:
            verify_answer(answer)

    def live_fuzzer(self):
        corpus = self.log / "corpus"
        corpus.mkdir(exist_ok=True)
        rng = random.Random(79171)
        for i in range(12):
            (corpus / f"seed-{i}").write_bytes(rng.randbytes(8 + 16*i))
        command = [self.fuzz, corpus, "-runs=10000", "-seed=89171", "-max_len=512",
                   "-timeout=5", "-rss_limit_mb=1536", "-print_final_stats=1",
                   "-artifact_prefix=" + str(self.log) + "/"]
        result = self.command(command, timeout=180)
        (self.log / "libfuzzer.log").write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stderr[-6000:]
        assert "stat::number_of_executed_units: 10000" in result.stderr, "incomplete campaign"
        files = sorted(corpus.iterdir(), key=lambda p: hashlib.sha256(p.read_bytes()).hexdigest())[:256]
        answers = self.measured_inputs([p.read_bytes() for p in files], "live")
        cases = [a["case"] for a in answers]
        counts = {"entries": len(files), "modes": len({c["mode"] for c in cases}),
                  "topologies": len({canonical(topology(c)) for c in cases})}
        self.metrics["live_diversity"] = counts
        self.details["diversity.live"] = counts["modes"] >= 4 and counts["topologies"] >= 16

    def run(self):
        self.test("build", self.build)
        if self.details["build"]:
            for mode in (*ref.MODES, "extended"):
                self.test("correctness."+mode, lambda mode=mode: self.fixtures(mode))
            for name, method in (("comparison", self.comparison), ("composition", self.composition),
                                 ("injection", self.injection), ("bindings", self.binding)):
                self.test("correctness."+name, method)
            self.test("determinism_replay", self.determinism)
            rng = random.Random(81043291)
            blobs = [rng.randbytes(rng.randint(16, 512)) for _ in range(1024)]
            answers = self.measured_inputs(blobs, "random")
            self.test("diversity.measurement", lambda: self.diversity([a["case"] for a in answers]))
            self.test("diversity.sensitivity", self.sensitivity)
            self.test("libfuzzer", self.live_fuzzer)
        reward = score(self.details, self.metrics)
        (self.log / "reward.json").write_text(json.dumps(reward, indent=2)+"\n")
        (self.log / "details.json").write_text(json.dumps(
            {"checks": self.details, "metrics": self.metrics, "failures": self.failures}, indent=2)+"\n")
        print(json.dumps(reward), flush=True)
        return 0 if reward["overall"] == 1 else 1


if __name__ == "__main__":
    log = Path(os.environ.get("VERIFIER_LOG", "/logs/verifier"))
    log.mkdir(parents=True, exist_ok=True)
    (log / "reward.json").write_text(json.dumps({
        k: 0.0 for k in ("overall", "input_validity_rate", "semantic_validity_rate",
                        "oracle_correctness", "diversity")})+"\n")
    raise SystemExit(Verifier(os.environ.get("APP_ROOT", "/app"), log).run())
