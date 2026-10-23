#!/bin/bash
set -euo pipefail
mkdir -p output/archive
if [ -f output/claim-plan.xlsx ]; then
    cp output/claim-plan.xlsx output/archive/claim-plan-1.xlsx
fi
if [ -f output/plan.json ]; then
    cp output/plan.json output/archive/claim-plan-1.json
fi
if [ -f output/settlement.xlsx ]; then
    cp output/settlement.xlsx output/archive/claim-plan-1-settlement.xlsx
fi
