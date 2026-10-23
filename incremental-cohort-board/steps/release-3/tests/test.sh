#!/bin/bash
set -euo pipefail
export BOARD_RELEASE=3
exec bash /tests/run.sh
