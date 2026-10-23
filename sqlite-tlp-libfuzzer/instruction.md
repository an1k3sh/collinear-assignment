# Implement a C++ libFuzzer-driven SQLite TLP tester

A database team needs a small, trustworthy metamorphic fuzzing target. Implement
the missing C++ components in `/app/src/generator.cpp` and `/app/src/engine.cpp`.
Read `docs/contract.md`, `include/tlp.hpp`, and the protected harness first.

Deliver:

1. A deterministic byte-to-case decoder that synthesizes bounded database rows
   and compositional SQL expressions. Arbitrary byte sequences, including empty
   ones, must yield valid cases. Input changes must affect both data and query
   structure. A fixed catalogue with randomized constants is insufficient.
2. Correct baseline/true/false/NULL query compilation for WHERE, existing-WHERE,
   DISTINCT, GROUP BY, HAVING, COUNT, SUM, AVG, MIN, and MAX.
3. Correct typed multiset comparison and aggregate recomposition, including
   weighted AVG, NULL/empty aggregates, shared groups, and duplicate HAVING
   projections. Detect injected mismatches and never swallow execution errors.
4. A working sanitizer-instrumented `tlp_fuzz` executable and replay through
   `tlp_cli`. The protected harness already handles libFuzzer's binary inputs,
   SQLite execution, JSON-line inspection, and replay; wire your implementation
   to its interfaces. You may add C++ helpers under `src/` and your own tests.

Do not modify CMakeLists.txt, include/, harness/, docs/, public_tests/, or replace
SQLite. Do not use network services or inspect verifier/oracle files. No Python
generator, subprocess generator, runtime code generation, or downloaded code.
The C++ target must do the work. The installed nlohmann JSON library is allowed.

Build and inspect:

```
cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=clang++-16
cmake --build build -j2
python public_tests/smoke.py build/tlp_cli
mkdir -p corpus reports
printf 'initial-seed' > corpus/seed
build/tlp_fuzz corpus -runs=10000 -max_len=512 -seed=123 \
  -artifact_prefix=reports/
build/tlp_cli replay corpus/seed
```

The verifier rebuilds from source and runs actual libFuzzer campaigns. It
independently validates schemas, prepares and executes all four SQL queries,
compares their meaning against reference queries on original and changed data,
and tests recomposition separately. No discovery of a real SQLite bug is
required. Valid SQL is not automatically a valid TLP transformation.

Diversity is measured on unseen deterministic byte corpora, controlled input
mutations, and a corpus produced by an actual libFuzzer run. The exact published
thresholds and scoring gates are in `docs/contract.md`. Neither SQL formatting
nor source similarity is graded. Example seeds and constructive/stratified
generation are allowed, but a data-only randomizer or fixed case catalogue
cannot meet the structural requirements. A template may be a grammar production;
templates must compose into genuinely different expression trees.
