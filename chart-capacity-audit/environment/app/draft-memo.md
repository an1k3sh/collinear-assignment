# Draft capacity memo -- requires independent review

The monitoring export covers 08:00--12:00 UTC on 14 September. I recommend
two new blocks for Alder, one for Delta, and none for Birch or Cedar.
The reasoning below has NOT been verified; do not treat it as source data.

* **D1:** Alder has the largest failed-request count over the usable windows:
  its failure-rate line is generally highest, so it should take priority.
* **D2:** To report the fleet failure percentage, take the arithmetic mean
  of the four regional failure percentages. Each region counts equally.
* **D3:** Delta's W1 and W2 are appropriate inputs to its capacity workload,
  because the report shows measured requests and failures in those windows.
* **D4:** Cedar's absent W7 and W8 bars represent measured zero traffic,
  so those two intervals should be treated as normal zero-request windows.
* **D5:** Cedar's last two usable latency windows do not meet the policy's
  persistent-high-latency eligibility condition.
* **D6:** The deployment at 10:00 UTC caused Birch's failure rate to fall.
  The charts establish that causal explanation.

Please correct this memo and produce an allocation under the actual written
policy, not just a revised opinion.
