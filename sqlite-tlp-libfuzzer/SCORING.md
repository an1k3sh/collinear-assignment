# What is measured

## Not just a C++ random SQL printer

The protected build links the actual LLVM libFuzzer runtime and instruments
the candidate's C++ sources with libFuzzer coverage, AddressSanitizer and
UndefinedBehaviorSanitizer. A callback consumes bytes, generates a database
and case, runs four queries, and aborts on an exception or mismatch. There is
no Python generator behind the target.

## Three independent evidence sources

1. **Unseen input corpus:** 1,024 varied byte sequences. Count different data,
   complete cases, expression structures and identifier-erased topologies.
2. **Counterfactual inputs:** 64 base inputs, each with four independently
   replaced payload quarters: 320 executions. Changes must reach both the
   generated case and query topology, not just a fixed-template selector.
3. **Actual libFuzzer corpus:** run 10,000 instrumented executions, collect the
   coverage corpus, and independently inspect up to 256 entries.

Instrumentation coverage is recorded, but high C++ edge coverage is not
treated as proof of SQL diversity. All structural and semantic counts are
computed by the verifier. Exact thresholds are public in the contract.

## Syntax versus semantics

Each observed input has separate counts:

* attempted inputs, including requests that fail or produce no output;
* emitted cases;
* schema-valid cases;
* executable cases: all four statements prepare and execute independently;
* semantic matches: baseline and EACH partition match independently rendered
  SQL, and reported/composed results are correct.

Compiled plans are also executed against changed table contents. This rejects
compilation that embeds answers from the original data. Testing only
`baseline == recomposed` would miss four consistently wrong queries, so it is
not sufficient here.

Input validity is executable/schema-valid divided by attempted inputs.
Semantic validity uses the same denominator. A result mismatch does not reduce
syntactic input validity; it is handled separately. Candidate success flags are
not trusted.

## Correctness and diversity scores

Fourteen equally weighted correctness families:

* ten TLP categories: WHERE, WHERE Extended, DISTINCT, GROUP BY, HAVING,
  COUNT, SUM, AVG, MIN, MAX;
* typed bag comparison, independent synthetic composition, executor
  injection/error handling, and bound literals.

The oracle-family tests use 219 independently constructed fixtures. Synthetic
states explicitly test average-of-averages, NULL versus zero, groups appearing
in only one partition, and duplicate HAVING projections.

Seven equally weighted diversity families:

1. mode/source/filter/grouped-aggregate coverage;
2. database and complete-case uniqueness;
3. structural and topology uniqueness;
4. non-vacuous partition occupancy and semantic edge cases;
5. expression grammar/operator coverage;
6. payload sensitivity;
7. live libFuzzer corpus diversity.

`overall` is zero if any mandatory gate fails:

* protected harness/build;
* all fourteen correctness families;
* both validity rates exactly 1;
* deterministic generation and fresh replay;
* real sanitizer/libFuzzer campaign completion;
* diversity families 2, 3, 4, 6 and 7.

Otherwise `overall = diversity`. Thus coverage/grammar can earn partial credit
after the core requirements pass, but fixed inputs, literal/data-only
variation, prefix-only selectors, and unsound TLP cannot be compensated for by
other categories.

No bug-discovery reward, LLM judge, source similarity, formatting requirement
or speed bonus is used.

## What this does not prove

No finite black-box verifier can prove that an adversarial implementation
contains no hardcoded catalogue. This verifier rejects representative catalogue
and data-only implementations and demands hundreds of independently observed
structures, multiple input-sensitive regions and a live fuzzing corpus.
It measures substantial behavior, not an absolute absence-of-hardcoding claim.
The bounded grammar is not all of SQLite; windows, collations, arbitrary SQL,
floating-point inputs and aggregate DISTINCT are deliberately out of scope.
