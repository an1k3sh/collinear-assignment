#!/bin/bash
set -euo pipefail
export BOARD_RELEASE=1
exec bash /tests/run.sh
