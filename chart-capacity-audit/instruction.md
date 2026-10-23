# Audit a chart-only capacity recommendation

You are the analyst reviewing a capacity request for a regional API service.
Only the exported dashboard images survived; the original metrics export is
unavailable. A draft memo recommends buying three capacity blocks. Audit its
claims and replace its recommendation using the supplied operational policy.

Read `/app/policy.md`, `/app/deliverables.md`, and `/app/draft-memo.md`.
The primary evidence is four PNG charts under `/app/report/`. Open them with
your native image-viewing tool, or serve `/app/report/index.html`:

```
python -m http.server 8080 --bind 0.0.0.0 --directory /app/report
```

The HTML is an offline viewer, not a data export. It embeds the same PNGs and
provides zoom controls. All required values are visually recoverable. If your
harness has no working way to view images, report that blocker: do not guess
values. Such a trial is not evidence of chart-reasoning failure.

## Deliverables

Create under `/app/submission/`:

1. `observations.json`: all 32 region/window records, with chart readings,
   bounded uncertainty, status and source-panel citations.
2. `analyze.py`: a Python-standard-library analysis program that reads the
   observations and policy, computes the requested statistics and allocation,
   and writes `analysis.json`.
3. `analysis.json`: the result of executing that program on your observations
   and `/app/policy.json`.
4. `audit.json`: decisions on the six numbered memo claims, with evidence
   references and short explanations.
5. `audit.md`: a concise human-readable corrected recommendation, uncertainty
   discussion and explanation of the main errors.

The exact interfaces are documented in `deliverables.md`. Code must work on
other valid observation values and supported policy settings; do not hardcode
the answer for this report. The verifier runs fresh calculations on small
counterfactual inputs to check this.

## What matters

The charts use requests **per minute**, failure percentages, and interval p95
latency. Distinguish unknown observations from zero. Use the status timeline to
decide which observations belong in the capacity calculation. Do not average
regional percentages as if regions had identical traffic.

Apply the written allocation rule, not your own theory of how capacity affects
latency. Report correlation as correlation: the deployment marker alone does
not establish causation. Demonstrate whether the allocation survives the
permitted uncertainty in the readings, rather than claiming unjustified
precision.

Do not modify the supplied report, policy, draft or interface documentation.
Do not inspect oracle/verifier files. Do not use network data or model APIs.
All analysis is local. There is no requirement to discover unavailable raw
metrics, use OCR, or produce pixel-identical annotations.

## Grading

Five components are reported: extraction, calculations, allocation, claim
audit, and reproducibility. Critical gates require correct maintenance/missing
semantics, supported eligibility and allocation, weighted totals within
published uncertainty bounds, valid source citations, faithful fresh program
execution and counterfactual behavior. A critical failure gives overall zero;
other component results remain visible. Full success requires every component.
Exact criteria and numeric tolerances are in the supplied documentation.
