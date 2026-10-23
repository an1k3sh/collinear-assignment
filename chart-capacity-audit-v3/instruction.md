# Reconcile a dashboard export and prepare a capacity rollout

You are reviewing a change request for a multi-region API platform. An analyst
assembled it from screenshots while telemetry exporters were being restarted.
One export page was subsequently corrected. The original time series are not
available. Finance wants a reproducible proposal, not a ranking copied from
the dashboard.

Your evidence is in `/app`:

* `report/`: nine raster pages and an offline HTML viewer. One page is superseded.
* `registry.csv`: display-name to target/region/service mapping.
* `export-manifest.json` and `corrections.md`: chart revisions and source authority.
* `operations.json`: window boundaries, reset events and maintenance exclusions.
* `planning.json`: prices, resource limits, rollout restrictions and risk weights.
* `policy.md`: telemetry semantics and planning rules.
* `draft-review.json`: eight claims awaiting adjudication.
* `interfaces.md`: deliverable schema and executable interface.
* `execution-policy.md`: future rollout jobs, readiness, dependencies, forecast
  cases and the separate max-min scheduling objective.

Inspect these sources, reconcile the report, and create:

1. A source inventory selecting authoritative pages and explaining rejection
   of the obsolete export.
2. Chart readings with bounded uncertainty and per-series source citations.
3. A reusable Python-standard-library pipeline reconstructing each traffic
   interval, joining the appropriate latency samples, and calculating an
   admissible capacity rollout.
4. A numerical analysis, an eight-claim audit and a decision memorandum with
   traceable evidence, resource use, unserved risk and uncertainty.
5. An independently optimized executable change schedule, including per-slot
   state, forecast-case risk, and bounds for its shared error observations.
   Do not assume that the static allocation is the best timed schedule.

Use `/app/submission/` for deliverables. Do not modify supplied evidence or
read verifier/oracle files. Do not use network data, model APIs or external
datasets. No OCR implementation is required: visual reading and manual
transcription are allowed.

View PNGs using native image tools, or serve the local HTML:

```
python -m http.server 8080 --bind 0.0.0.0 --directory /app/report
```

Starting a server does not give a text-only harness visual access. If no image
tool works, report the blocker; that is not a chart-reasoning failure.

## What makes this an audit

Counter levels are not interval volumes, and a restart is not negative traffic.
Missing endpoints cannot simply be filled with zero. A deployment/reset event
does not by itself prove a causal performance effect. Percentiles cannot be
averaged or pooled by voting across windows. A high-risk target may be
ineligible for this rollout. The budget is not the only resource constraint.

Use the published definitions rather than assumptions. Persist intermediate
interval decisions so a reviewer can see why an observation was included or
excluded. Your program must also handle valid changed readings and operating
policies without being rewritten. The verifier exercises fresh scenarios.

## Success and grading

The report is deliberately readable. Value labels and zoom are allowed;
this is not a tiny-text or exact-pixel test. Readings have public tolerances.
The final nominal plan must be feasible and optimal for your admissible
readings, with a correct worst-case comparison against all feasible rivals.
If a counterfactual does not support a unique robust plan, report that instead
of inventing certainty.

Extraction, reconciliation, workload/latency calculations, planning, claim
audit and reproducibility are reported separately. Critical failures in
source authority, exclusions, counter reconstruction, pooled latency,
resource-constrained planning or fresh execution give zero overall. Detailed
partial scores remain visible. Exact checks are in `interfaces.md`.
