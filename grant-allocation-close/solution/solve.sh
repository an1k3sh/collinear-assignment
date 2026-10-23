#!/bin/sh
set -eu
python /solution/repair.py
cat > /app/submission/REPAIR_REPORT.md <<'EOF'
# Grant close repair

The ledger helper selects only the highest cutoff-known revision within exact
text program/item keys, then applies status and effectivity. Each counted
signed currency amount is converted and rounded to cents before aggregation.
Approval, available expense balance and program maximum determine the cap.

The Allocation sheet redistributes capped excess across the remaining weighted
programs. Eight rounds suffice for eight programs; no iterative calculation
setting is needed. Final fractional remainders determine penny distribution,
with the committee's integer tie ranks used for equal remainders. Summary
awards and unspent authorization reconcile, and the chart references live
Summary names/awards. Ledger helpers cover every supported row through 501.

Source values and the prior close are retained. LibreOffice recalculation was
used to fill the saved caches; the workbook is left in automatic calculation.
EOF
