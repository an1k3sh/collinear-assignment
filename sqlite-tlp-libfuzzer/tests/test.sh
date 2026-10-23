#!/bin/sh
set -eu
mkdir -p /logs/verifier
export ASAN_OPTIONS=detect_leaks=1:quarantine_size_mb=32
export UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1
python /tests/verify.py
