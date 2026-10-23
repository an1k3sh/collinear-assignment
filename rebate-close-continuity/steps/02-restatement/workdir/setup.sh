#!/bin/bash
set -euo pipefail
mkdir -p output/archive
if [ -f output/settlement.xlsx ]; then
    cp output/settlement.xlsx output/archive/close-1.xlsx
fi
