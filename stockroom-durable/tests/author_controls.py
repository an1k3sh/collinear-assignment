"""Semantic negative controls, for disposable oracle containers only."""
from pathlib import Path
import json

import durable_checks


def main():
    machine = Path("/app/stockroom/durable.py")
    cli = Path("/app/stockroom/__main__.py")
    originals = {machine: machine.read_text(), cli: cli.read_text()}
    cases = dict(durable_checks.continuation_cases())
    controls = [
        ("drop-prepause-events", machine,
         'state["frames"] = self.durable_frames',
         'state["frames"] = self.durable_frames\n        state["events"] = []',
         cases["nested-recovery-error-shadowing"]),
        ("reset-resumed-step-budget", machine,
         'setattr(self, key, value)',
         'setattr(self, key, value)\n            self.stats["steps"] = 0',
         cases["fatal-statement-budget-is-cumulative"]),
        ("reset-resumed-transaction-counters", machine,
         'setattr(self, key, value)',
         'setattr(self, key, value)\n            self.stats["committed"] = 0',
         cases["nested-commit-before-pause-outer-abort"]),
        ("lose-rollback-bindings", machine,
         'self.scope_store[key].clear()\n            self.scope_store[key].update(values)',
         'pass',
         cases["shadowed-bindings-survive-two-rollbacks"]),
        ("lose-rollback-hold-snapshot", machine,
         'self.holds = snapshot["holds"]', 'pass',
         cases["pause-not-a-commit-and-counters"]),
        ("lose-recovery-error-code", machine,
         'diagnostic.get("code"))', '"WRONG")',
         cases["nested-recovery-error-shadowing"]),
        ("treat-pause-as-commit", machine,
         'self.pause_count += 1',
         'self.pause_count += 1\n            self.stats["committed"] += 1',
         cases["pause-not-a-commit-and-counters"]),
        ("accept-changed-source-identity", cli,
         'saved = load(args.resume, identity) if args.resume else None',
         'saved = load(args.resume, json.loads(args.resume.read_text())["identity"]) if args.resume else None',
         lambda: durable_checks.corrupted_case("program-change")),
        ("rewrite-checkpoint-on-completion", cli,
         'publish(args.out, result)',
         'publish(args.out, result)\n        if args.resume:\n            publish(args.resume, {"consumed": True})',
         cases["pause-in-callee-and-return"]),
    ]
    results = []
    try:
        for name, path, old, new, run in controls:
            for target, source in originals.items():
                target.write_text(source)
            if originals[path].count(old) != 1:
                raise AssertionError(f"Non-unique mutation: {name}")
            path.write_text(originals[path].replace(old, new))
            try:
                run()
            except AssertionError as error:
                results.append({"mutant": name, "rejected": True, "reason": str(error)})
            else:
                raise AssertionError(f"Verifier accepted mutant {name}")
    finally:
        for path, source in originals.items():
            path.write_text(source)
    Path("/logs/verifier/controls.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"mutants_rejected": len(results), "total": len(controls)}))


if __name__ == "__main__":
    main()
