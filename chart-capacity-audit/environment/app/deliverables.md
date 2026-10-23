# Deliverable interfaces

All JSON must be UTF-8, with finite numeric values (not NaN/Infinity). Additional
human-readable notes are allowed; required keys must be present.

## observations.json

An object with `records`, a list containing exactly one record for every
region/window pair in the policy, and no duplicates:

```
{
  "records": [{
    "region": "Alder",
    "window": "W1",
    "status": "normal",
    "rate": [0, 0, 0],
    "failure_pct": [0, 0, 0],
    "p95_ms": [0, 0, 0],
    "sources": {
      "rate": "P1", "failure_pct": "P2", "p95_ms": "P3", "status": "P4"
    }
  }]
}
```

Zeros here illustrate the shape, not report readings. Every metric is an
interval `[low,estimate,high]`; for unknown records, all three metrics are null.
The region/window pair locates the observation within each cited panel.

## analyze.py and analysis.json

Invocation (must work from any current working directory):

```
python /app/submission/analyze.py \
  --observations /app/submission/observations.json \
  --policy /app/policy.json \
  --out /app/submission/analysis.json
```

Return zero on success. Input filenames and output location may change.
Do not read private files or depend on working-directory state.

Output:

```
{
  "regions": {
    "Alder": {
      "included_windows": ["W1"],
      "latency_windows": ["W1"],
      "requests": 0,
      "failed_requests": 0,
      "failure_pct": null,
      "failed_bounds": [0, 0],
      "eligible": false
    }
  },
  "fleet": {"requests": 0, "failed_requests": 0, "failure_pct": null},
  "allocation": {"Alder": 0, "Birch": 0, "Cedar": 0, "Delta": 0},
  "expected_benefit": 0,
  "benefit_bounds": [0, 0],
  "robust_margin": null,
  "robust": true
}
```

Include all four regions. Window lists must follow the policy order.
`benefit_bounds` is the selected allocation's benefit evaluated using regional
failed-count bounds. `robust_margin` is defined in policy.md.

Numeric consistency with YOUR observations is checked with absolute tolerance
0.000001 plus relative tolerance 0.000001. This is calculation tolerance, not
visual extraction tolerance. Submitted chart intervals must also cover the
reference readings within their published maximum widths. A valid approximate
extraction is accepted; there is no demand for exact reconstructed raw data.

## audit.json

An object with `claims`, containing exactly one record per memo claim D1..D6:

```
{
  "claims": [{
    "id": "D1",
    "verdict": "incorrect",
    "evidence": [{"panel": "P1", "region": "Alder", "window": "W1"}],
    "explanation": "Explain the observation and reasoning in your own words."
  }]
}
```

Verdicts: `correct`, `incorrect`, `unsupported`.
`incorrect` contradicts the charts or the written policy.
`unsupported` cannot be established from those sources.
Evidence references must use actual panel/region/window IDs and cover the
quantities relevant to the claim. D1/D2 require P1, P2 and P4; D3 P4;
D4 P1 and P4; D5 P3 and P4; D6 P2 and P4. Cite at least one Delta W1/W2
status for D3, Cedar W7/W8 for D4, and Cedar W5/W6 for D5. For D6 cite Birch
on both sides of the deployment (W4 and W5). Other claims can cite representative
observations plus the computed totals in the explanation. An explanation is
required, but no exact wording or LLM-based prose score is used.

## audit.md

State the corrected allocation, the principal errors in the draft, and whether
the allocation is robust to your reading intervals. Include panel references.
This report is for human review. Its existence/nonemptiness is checked, but
prose style is not a reward dimension; substantive decisions are graded from
the structured files.

## Score

* extraction: correctly read region/window records / 32. A record needs the
  right status, metric intervals covering the readings within the stated
  widths, and the correct source IDs.
* calculations: correctness of the four regional summaries plus fleet summary,
  compared against fresh independent calculation from your observations / 5.
* allocation: nominal allocation, expected benefit, benefit bounds, and robust
  certificate all correct, as one family.
* claim_audit: correct verdict and valid evidence for each claim / 6.
* reproducibility: fresh original-input execution, all valid counterfactual
  executions, invalid-input diagnostics, and nonempty audit.md / 4.

Overall is zero unless critical gates pass: all statuses and citations; all
calculations; all allocation checks; quantitative totals within the maximum
chart-reading envelopes; correct verdicts/evidence for D1,D2,D3,D4,D6; and all
reproducibility families. Otherwise:

`overall = 0.25*extraction + 0.25*calculations + 0.20*allocation
         + 0.15*claim_audit + 0.15*reproducibility`.

Full success requires 1.0 in all components. Private tests stay within this
public interface; they do not grade image-tool choice, rendering similarity,
file creation order or prose phrasing.
