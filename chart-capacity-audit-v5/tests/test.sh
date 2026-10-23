#!/bin/sh
set -eu
mkdir -p /logs/verifier
python /tests/grade.py
