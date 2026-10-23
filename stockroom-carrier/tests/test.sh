#!/bin/sh
set -eu
mkdir -p /logs/verifier
cd /app
python /tests/test_semantics.py
