#!/bin/sh
set -eu
cp /solution/engine.cpp /app/src/engine.cpp
cp /solution/generator.cpp /app/src/generator.cpp
cmake -S /app -B /app/build -G Ninja -DCMAKE_CXX_COMPILER=clang++-16
cmake --build /app/build -j2
python /app/public_tests/smoke.py /app/build/tlp_cli
