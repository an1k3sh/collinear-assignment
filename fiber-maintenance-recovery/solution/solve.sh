#!/bin/sh
set -eu
mkdir -p /app/submission
cp /solution/topology.json /app/submission/topology.json
cp /solution/build_plan.py /app/submission/build_plan.py
python /app/submission/build_plan.py --data /app/data --topology /app/submission/topology.json --output /app/submission/maintenance.json
cat > /app/submission/handover.md <<'EOF'
# Maintenance release

The topology transcribes each cable's two drawn terminations, combining room
and spine sheets by their shared node IDs. Crossings are not graph vertices.
The version selector uses only inventory known at the planning cutoff.

For every phase the solver removes blocked and outage cables, reserves both
copies of each protected service, enforces shared undirected capacity, and
separates primary and secondary risk groups. Dark-cable activations are charged
once across all phases and constrained by the authorization. Directional arcs
are ordered into simple source-to-target cable paths for the release artifact.
EOF
