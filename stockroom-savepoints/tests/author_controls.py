"""Run only in a disposable oracle-populated container; never part of grading."""
from __future__ import annotations

import json
from pathlib import Path

import test_semantics as checks


def main() -> None:
    checks.language_cases()
    checks.transaction_cases()
    checks.inventory_cases()
    checks.failure_cases()
    checks.workflow_cases()
    runtime = Path("/app/stockroom/runtime.py")
    original = runtime.read_text()
    controls = [
        ("omit-binding-rollback",
         "scope.clear()\n                scope.update(saved)", "pass",
         ["nested-commit-outer-abort", "rollback-with-shadowed-binding"]),
        ("shallow-hold-snapshot",
         "hold_snapshot = copy.deepcopy(self.holds)", "hold_snapshot = dict(self.holds)",
         ["rollback-hold-records-not-just-map"]),
        ("leak-aborted-events",
         "del self.events[event_length:]", "pass",
         ["nested-commit-outer-abort", "recover-inside-outer-remains-tentative"]),
        ("ignore-existing-reservations",
         'return self.onhand(warehouse, sku) - sum(',
         'return self.onhand(warehouse, sku) - 0 * sum(',
         ["hold-conservation-and-tombstones", "workflow-must-respect-existing-holds"]),
        ("catch-fatal-as-domain",
         'if error.category != "DOMAIN":', "if False:",
         ["fatal-not-caught-by-domain-handler", "step-limit-not-caught"]),
        ("rollback-successful-return",
         'except Flow:\n            self.stats["committed"] += 1',
         'except Flow:\n            self.warehouses = inventory_snapshot\n'
         '            self.holds = hold_snapshot\n'
         '            del self.events[event_length:]\n'
         '            self.stats["committed"] += 1',
         ["return-commits-exited-transactions", "loop-control-commits-and-stats"]),
        ("floor-negative-division",
         'quotient = -quotient', 'quotient = lv // rv',
         ["precedence-and-scalar-types"]),
        ("erase-inner-commit-counter",
         'self.stats["rolled_back"] += 1',
         'self.stats["committed"] = 0\n            self.stats["rolled_back"] += 1',
         ["nested-commit-outer-abort", "callee-return-does-not-commit-caller"]),
    ]
    records = []
    try:
        for name, old, new, selectors in controls:
            if original.count(old) != 1:
                raise AssertionError(f"Control patch not unique: {name}")
            runtime.write_text(original.replace(old, new))
            rejected = []
            for selector in selectors:
                case = next(row for row in checks.CASES if row["name"] == selector)
                try:
                    checks.run_case(case)
                except AssertionError as error:
                    rejected.append({"case": selector, "reason": str(error)})
            if not rejected:
                raise AssertionError(f"Unsound verifier: accepted mutant {name}")
            records.append({"mutant": name, "rejected_by": rejected})
    finally:
        runtime.write_text(original)
    output = Path("/logs/verifier/controls.json")
    output.write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps({"mutants_rejected": len(records), "total_mutants": len(controls)}))


if __name__ == "__main__":
    main()
