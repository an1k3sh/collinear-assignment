# Cash-claim batching policy

## Input and historical state

CLI:

```
python plan.py --settlement PATH --claims PATH --as-of YYYY-MM-DD \
  --output PATH [--prior-plan PATH]
```

Read each Summary group/quarter's CURRENT entitlement dollars from the supplied
settlement workbook, converting to integer cents. Evaluate formulas on a copy
if caches are absent; do not assume caches must exist. This is capacity, NOT
the adjustment/journal column. Never modify the settlement input.

Claims input sheets:

* `Claims`: claim_id, revision, recorded_at, group, quarter, amount_cents,
  priority, review_minutes, rail, family, requires_id, status.
* `Paid`: receipt_id, revision, recorded_at, group, quarter, amount_cents, status.
* `Suppliers`: group, setup_minutes, min_batch_cents, max_claims.
* `Rails`: rail, max_claims.
* `Limits`: name, value (contains review_minutes).

All amounts, times, thresholds, revisions and limits are nonnegative integers;
claim amounts and revisions are positive. Priority is 1, 2 or 3 (1 highest).
Dates are ISO strings. For Claims and Paid independently, discard revisions
recorded after as-of, then select greatest numeric revision per ID, regardless
of physical order. Identical replayed revisions count once.

Only OPEN claims may be selected. PAID and BLOCKED claims remain in the audit
table but are not selectable. Only latest CONFIRMED Paid receipts count as cash;
VOID receipts count zero. An earlier CONFIRMED version of a VOID receipt must
not reappear. Paid receipts are the ONLY cash deductions: do not also subtract
PAID claims, previous plan totals, or earlier journals.

Available cents per (group, quarter) =
max(0, current entitlement cents - confirmed paid cents).
All supplied keys have a settlement Summary row and a Suppliers row.
All rails exist. A requires_id, when present, refers to another claim in the
same group, forms no cycle, and means both must be selected IN THIS SAME BATCH.
It is not satisfied by a previously paid or previously recommended claim.

## Feasibility

Claims are indivisible: select 0 or 1 of each current claim; no partial amounts.
Enforce all of the following:

1. Sum selected amount_cents per group/quarter <= available cents for that key.
2. Total review time <= Limits.review_minutes. Include each selected claim's
   review_minutes AND one setup_minutes charge per supplier group with any
   selected claims. Do NOT charge setup separately for each quarter or claim.
3. Selected count per rail <= that rail's max_claims (counts, not dollar caps).
4. Selected count per supplier group <= Suppliers.max_claims.
5. A supplier with any selected claim must have total selected face value
   across its quarters >= its min_batch_cents. An unused supplier has no minimum.
6. At most one claim per nonempty family. Families denote alternative packets
   for the same evidence; family names are scoped to their supplier group.
7. Selecting a claim with requires_id requires selecting that prerequisite.

The empty plan is always feasible, even if every supplier minimum is positive.
No other diversity, fairness, cash-budget or mandatory-claim constraints apply.

## Objective: exact lexicographic optimum

Among feasible plans:

1. Maximize total selected priority-1 cents.
2. Holding that optimum fixed, maximize priority-2 cents.
3. Holding both fixed, maximize priority-3 cents.
4. Holding all three fixed, minimize total review minutes INCLUDING setups.
5. Finally minimize selected claim count.

The objective vector is `[p1_cents, p2_cents, p3_cents, -review_minutes, -count]`;
lexicographically greatest wins. Any plan with the optimal vector is accepted.
Do not substitute ratios, weighted heuristics or one weighted objective without
proving dominance for the actual input. All input variations use the same rules.

## Deliverables and refreshability

`plan.py` must create the requested parent/output path, exit nonzero on invalid
data or optimizer failure with an explanation, leave all CLI inputs untouched,
and write `plan.json` beside that output. It must handle new valid claims,
receipt/claim revisions, changed prices/capacities, supplier setup/minimum/count
limits, review capacity and rail limits. It must not hardcode an optimal ID set.

The output XLSX retains all nonempty input claim-sheet cell values and adds:

* `Plan`: columns claim_id, group, quarter, amount_cents, priority,
  review_minutes, rail, selected. One row per current claim known at cutoff,
  including nonselectable ones. selected is an integer 0 or 1.
* `Capacity`: columns group, quarter, entitlement_cents, paid_cents,
  available_cents, selected_cents, remaining_cents. One row per financial
  Summary key, including zero balances. selected_cents and remaining_cents must
  be live formulas connected to Plan selections. Cached values are optional.

Write `plan.json` with at least:

```
{
  "as_of": "YYYY-MM-DD",
  "claims_sha256": "<hash of input claims workbook bytes>",
  "settlement_sha256": "<hash of input settlement workbook bytes>",
  "prior_plan_sha256": null,
  "selected_ids": ["..."],
  "objective": [100, 200, 300, -10, -2],
  "review_minutes": 10,
  "used_by_rail": {"WIRE": 1, "PORTAL": 1}
}
```

prior_plan_sha256 is null when no --prior-plan is supplied, otherwise that
file's SHA256. The prior recommendation is evidence only: it does not change
eligibility, constraints or the objective. Include every configured rail in
used_by_rail, even if unused. Orders of rows and IDs are unconstrained.
