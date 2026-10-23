# Corrected capacity recommendation

Allocate **two blocks to Birch and one to Delta**. Allocate none to Alder or
Cedar. This maximizes the supplied planning benefit; it is not a causal
prediction of the actual effect of adding capacity.

Reading P1 and P2 together, multiplying mean requests/minute by the 30-minute
durations, and applying P4's per-region exclusions gives:

| Region | Requests | Failed requests |
|---|---:|---:|
| Alder | 60,000 | 3,840 |
| Birch | 504,000 | 16,170 |
| Cedar | 162,000 | 2,070 |
| Delta | 198,000 | 8,580 |

The fleet denominator is 924,000 requests; there are 30,660 failures. Compute
the percentage as the ratio of those totals, not an average of percentages.

P4 excludes Delta W1/W2 (maintenance) and Cedar W7/W8 (unknown). The latter are
not observed zeroes. P3 and P4 put Cedar below the persistent latency trigger;
Alder, Birch and Delta qualify.

The nominal selected benefit is 13,134 failed-request equivalents. The
analysis enumerates feasible allocations and cancels common coefficients
before bounding every difference. The chosen allocation remains optimal
through the reading intervals recorded in observations.json; analysis.json
contains the numerical bounds and positive worst-competitor margin.

The deployment marker in P4 and decline in P2 establish timing, not causation.
Claims D1--D4 are incorrect, D5 is correct, and D6 is unsupported. The
machine-readable audit includes panel/region/window evidence for each claim.
