# Audit of draft capacity memo (2026-09-14, W1-W8)

## Corrected recommendation
Under `/app/policy.json` (budget 3, max 2/region, trigger 300 ms, benefit fractions 0/0.4/0.6):

| Region | Normal windows (P4) | Requests | Failed (est. [low, high]) | Fail % | Last-2 p95 (P3) | Eligible | Blocks |
|---|---|---:|---:|---:|---|---|---:|
| Alder | W1-W8 | 60,000 | 3,840 [3,115, 4,603] | 6.40 | W7 330, W8 350 | yes | 0 |
| Birch | W1-W8 | 504,000 | 16,170 [14,869, 17,509] | 3.21 | W7 420, W8 440 | yes | **2** |
| Cedar | W1-W6 | 162,000 | 2,070 [1,670, 2,498] | 1.28 | W5 260, W6 270 | no | 0 |
| Delta | W3-W8 | 198,000 | 8,580 [7,886, 9,302] | 4.33 | W7 370, W8 390 | yes | **1** |

Fleet: 30,660 failed / 924,000 requests = **3.32%** (ratio of totals).

**Allocate 2 blocks to Birch and 1 to Delta, none to Alder or Cedar.** Planning benefit is 13,134
failed requests, with bounds [12,076, 14,226]. These benefit fractions are the policy's planning
weights. They do not predict how much failures will actually drop.

## Robustness
Readings use intervals of ±40 req/min (P1) and ±0.2 pp (P2). P3 labels are exact. The closest
competitor is Birch 1 / Delta 2. Paired worst case: 0.2·14,869.2 − 0.2·9,302.4 = **1,113.36 > 0**.
The allocation therefore holds across all permitted reading uncertainty (`robust: true`). Every
last-two p95 value is at least 30 ms from the trigger, so eligibility is also unambiguous.

## Principal errors in the draft
- **Wrong allocation.** The draft proposed 2 blocks for Alder and 1 for Delta. Alder has a high failure *percentage* (P2) but low traffic
  (P1 has its own scale, 200-300 req/min). It has the third-largest failed count. Birch has the most (D1 incorrect).
- **Unweighted average (D2 incorrect).** Averaging regional percentages gives about 3.81%. Weighting by traffic gives 3.32%.
- **Maintenance included (D3 incorrect).** Delta W1/W2 are MAINTENANCE in P4. They are transcribed but excluded.
- **Unknown treated as zero (D4 incorrect).** Cedar W7/W8 are UNKNOWN in P1 and P4. They are recorded as null, not zero.
- **D5 correct.** Cedar's last normal p95 values (W5 260, W6 270 ms) do not exceed 300 ms.
- **Causal overreach (D6 unsupported).** Birch's failure rate fell from 3.5% to 3.0% across the 10:00 deployment (P2, P4). It was
  already falling before then, and a single marker shows only correlation.

Files: `observations.json` (32 records), `analyze.py` -> `analysis.json`, `audit.json`.
