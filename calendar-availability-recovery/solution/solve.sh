#!/bin/sh
set -eu
mkdir -p /app/submission
cp /solution/rebuild.py /app/submission/rebuild.py
python /app/submission/rebuild.py --source /app/input --output /app/submission
cat > /app/submission/REPORT.md <<'EOF'
# Booking recovery

Revisions are selected within calendar/UID/original-instance namespaces,
using sequence and timestamp at the publication cutoff. The finite recurrence
set is expanded in local calendar time, unioned with RDATE, and reduced by
EXDATE before detached changes are applied.

Original recurrence identity is retained across moves. Suffix changes use
wall-clock displacement; duration and transparency inherit independently.
Calendar-day duration and elapsed-hour duration use distinct calculations.
Instances are filtered by their final actual intervals. Busy blocks are
clipped and unioned, and candidate slots are checked with half-open boundaries.
EOF
