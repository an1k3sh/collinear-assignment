# sqlite-tlp-libfuzzer: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `sqlite-tlp-cpp-copilot-opus-01` | `copilot-cli` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./sqlite-tlp-libfuzzer -a oracle
harbor run -p ./sqlite-tlp-libfuzzer -a claude -m opus-5-5
harbor view ./jobs
```

The illustrative `claude` alias is provider/version dependent. Harbor 0.24.0 exposes `claude-code` for the native Claude Code harness; supply the actual available model ID, credentials and high reasoning configuration. See the detailed experiment commands below for the measured harness, rather than relabeling historical results.

## Checklist and fairness audit

* The task prompt states input locations, protected boundaries and durable deliverables. Only environment sources are copied into the agent image; reference solutions and tests are staged by Harbor separately.
* Metadata declares category, timeouts, resources and network policy. `public` network permits harness setup/inference; it is not an enforced offline sandbox.
* The Dockerfile pins the base image and declares dependencies. Validation uses fresh Docker containers on macOS Docker Desktop (Linux arm64); other architectures are not certified.
* Both shell entrypoints are executable. The verifier emits reward JSON or text under `/logs/verifier` on graded outcomes. Infrastructure errors must not be interpreted as model defects.
* Functional checks and existing alternate/mutation controls test the task's stated outcomes. A fresh untouched/no-op baseline is checked during collection validation; detailed verifier design and limitations follow below.
* Economic usefulness, long-horizon subgoals and provenance are recorded in the detailed notes. [LICENSES.md](LICENSES.md) inventories external tools and license sources.
* Versioned tasks reuse same-exercise work openly. They are not independent originality claims and are not ports of unrelated existing benchmarks.

## Detailed design and historical experiment notes

# C++ libFuzzer task run report

## Status

The C++ oracle passes native Harbor. Claude Opus 5.5 high also passed the C++
task in Copilot CLI 1.0.102, with all five reward fields at 1.0. There is
**no demonstrated frontier-model failure for this task**. This was not the
assignment's requested Claude Code harness. Earlier Python trials remain
separate evidence and are not relabeled as C++ trials.

Environment: pinned Python 3.12.12 Debian bookworm image, Clang/libFuzzer 16.0.6,
SQLite 3.40.1, nlohmann JSON 3.11.2. Docker Linux arm64. Application and verifier
were also exercised with network disabled.

## Opus trial: sqlite-tlp-cpp-copilot-opus-01

Model: `claude-opus-5.5`; reasoning: `high`, confirmed in the trajectory's
actual reasoning metadata; harness: Copilot CLI 1.0.102.
Trial: `sqlite-tlp-libfuzzer__QnFTcfS`. No infrastructure exception.
Total runtime: 18 minutes 45 seconds; agent execution: approximately
15 minutes 40 seconds. The frozen task files matched their pre-run hashes
after completion. No grader changes were made during or after this trial.

| Reward | Value |
|---|---:|
| Overall | 1.0 |
| Input validity | 1.0 |
| Semantic validity | 1.0 |
| Oracle correctness | 1.0 |
| Diversity | 1.0 |

All 1,600 independently inspected cases passed schema, execution and semantic
checks: 1,024 unseen-byte cases, 320 counterfactual cases and 256 live-corpus
cases. The unseen-byte corpus contained:

* 1,024 distinct cases, databases and structural fingerprints.
* 1,020 identifier-erased topologies.
* All nine modes, with 92..129 cases per mode.
* 90 three-way occupied cases and 788 nonempty baselines.
* 20 overlapping-group cases and 10 duplicate-projection HAVING cases.
* All payload quarters changed cases 64/64 times; topology changes were
  64, 61, 61 and 60 out of 64.

The verifier's actual libFuzzer campaign completed 10,000 executions, added
541 corpus entries and reported 123 MB peak RSS. The inspected live sample
contained all nine modes and 242 topologies.

### Why this was a pass, not a hardcoding loophole demonstrated by the run

The generated C++ source uses a compositional expression grammar. Leading
bytes make direct grammar decisions; remaining bytes seed local expansion of
projections, filters and database contents. It includes explicit edge values
and string dictionaries, which are allowed grammar ingredients rather than
a fixed catalogue of complete queries.

The trajectory shows substantial independent verification: the model wrote
its own schema/reference-SQL checker, checked original/changed/empty data,
adjusted row/NULL distributions to improve occupancy, and tested multiple
unseen corpora. It also ran a longer fuzz campaign; recorded tool output
confirms 118,850 executions over 171 seconds with no reported crash or mismatch.
Its separate test code is not the grading authority; the independent verifier
results above establish this trial's pass.

The bounded grammar, protected runtime and explicit interfaces made the task
tractable for this model. More requirements alone have not demonstrated a
capability failure. Do not increase thresholds after seeing the result and
then describe this frozen trial as a failure.

Evidence: [reward](evidence/opus-copilot-01/reward.json),
[checks and measurements](evidence/opus-copilot-01/details.json),
[trajectory](evidence/opus-copilot-01/trajectory.json),
[generated C++](evidence/opus-copilot-01/src/),
[frozen file hashes](evidence/opus-copilot-01/frozen-files.json).

## Native Harbor oracle: sqlite-tlp-cpp-oracle-01

All five reward fields were 1.0. Total Harbor runtime was approximately
47 seconds, well below the 600-second verifier and 7,200-second agent budgets.

| Corpus | Attempted | Schema-valid | Executable | Semantic matches |
|---|---:|---:|---:|---:|
| Unseen bytes | 1,024 | 1,024 | 1,024 | 1,024 |
| Input counterfactuals | 320 | 320 | 320 | 320 |
| Sampled live libFuzzer corpus | 256 | 256 | 256 | 256 |

All semantics above include original AND changed database contents. Boundary
and fresh-process replay checks additionally passed.

On the unseen corpus:

* 1,024 different cases and 1,020 different database contents.
* 1,019 structural fingerprints after removing data and literal values.
* 1,004 topologies after additionally removing column identities.
* All nine modes; 90..125 topologies per mode.
* 148 three-way occupied cases, 759 nonempty baselines.
* 29 overlapping-group cases and 23 duplicate-projection HAVING cases.
* 305 empty row-stage inputs and 118 all-NULL aggregate cases.
* 64/64 payload replacements changed both cases and topology in each quarter.

The real libFuzzer campaign completed 10,000 executions, added 363 corpus
entries and reported peak RSS 109 MB. The inspected live sample covered nine
modes and 253 topologies. Corpus size/coverage counts can vary across native
runs; those exact numbers are evidence, not grading thresholds.

## Grader validation and iteration

The first independent execution check exposed a bug in our protected C++
runtime: an unqualified helper named `bind` could resolve to `std::bind` when
given a temporary vector, leaving inserted columns NULL. Both sides of TLP
still agreed, which is precisely why equality alone is insufficient.
The helper was renamed and a hand-calculated public database witness added.
The full fixture, generated-input and native Harbor checks then passed.
This was an author harness bug, not a model failure.

Author unit tests verify:

* hand-calculated independent reference semantics;
* rejection of three identical "partition" queries;
* rejection of precomputed answers after changing data;
* correct denominators for schema errors, SQL errors and missing outputs;
* an executable mismatch remains syntactically valid.
* score arithmetic, every mandatory gate (including missing results), and
  partial-credit behavior.

All seven unit tests passed. After extracting the unchanged scoring formula
into a directly testable function, all sixteen recorded audit rewards were
recomputed and matched exactly. Expanded mismatch injection across all nine
modes passed for the oracle and both positive alternatives.

The full mutation audit passed: the oracle and two correct alternatives earned
1.0; all twelve faulty variants and the untouched scaffold earned 0.0. Full
results are recorded in the packaged evidence. Every
control must first compile successfully, so a compiler error cannot count as
detection of the intended fault. Positive alternatives wrap equivalent queries
and reverse row order. Negative controls target ignored/prefix-only inputs,
data-only variation, a 32-template catalogue, TLP mistakes and false success.
Notably, the ignored-input, prefix-only, data-only and catalogue controls all
had 100% syntactically and semantically valid SQL, yet earned zero overall
because they failed the required input-sensitivity/diversity gates.

Evidence:

* [Harbor reward](evidence/harbor-oracle/reward.json)
* [Harbor checks and measured counts](evidence/harbor-oracle/details.json)
* [Actual libFuzzer log](evidence/harbor-oracle/libfuzzer.log)
* [Full author audit summary](evidence/author/summary.json)
* [Verifier unit tests](evidence/unit-tests.log)

## Fairness and limitations

The task deliberately specifies a bounded AST rather than requiring arbitrary
SQL generation. All thresholds are public. Constructive generation, explicit
edge-case productions and deterministic local expansion of byte entropy are
allowed. The oracle hashes input bytes into a local PRNG and recursively
composes grammar productions; it does not select full queries from a catalogue.
This is one accepted design, not a mandated decoding format.

Independent reference tests and representative positive/negative controls
reduce false positives and negatives but cannot prove universal correctness.
Finite black-box sampling cannot rule out every adversarial hardcoded
catalogue. The system SQLite library is not coverage-instrumented; candidate
code and the harness are. This benchmarks generator/oracle engineering, not
the effectiveness of finding unknown SQLite engine bugs.

Before claiming assignment completion, run the target model in the requested
harness and analyze an actual substantive failure if one occurs. Do not
reinterpret a pass or infrastructure problem as such a failure.
