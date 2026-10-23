# Rebuild the April cash and receivables close

The controller has withheld sign-off on the April close. Independently
reconstruct the close from the supplied records, assess the existing draft,
and identify any unresolved discrepancies under the documented policy.

Using `POLICY.md` and `data/`, write `submission/reconcile.py` and run:
`python submission/reconcile.py --input data --output submission/close`.
Deliver `settlements.csv`, `aging.csv`, `summary.json`, and
`submission/REPAIR_REPORT.md` explaining discrepancies and checks.

Do not edit the evidence or input files. All amounts are integer cents; this is
a supplied-policy reconciliation, not an accounting-policy judgment. The same
script must work on other datasets satisfying the same policy, not just the
supplied records. The verifier checks economic allocations, not narrative wording.
Use Python's standard library; no network or credentials are needed.
