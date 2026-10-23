# incremental-cohort-board: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `cohort-opus-01` | `copilot_npm:NpmCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |
| `cohort-v2-opus-01` | `copilot_npm:NpmCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./incremental-cohort-board -a oracle
harbor run -p ./incremental-cohort-board -a claude -m opus-5-5 --resume-trajectory
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

# Incremental cohort board: task and run report

## Status

This is one newly authored, four-release Harbor task, not a collection of
alternative tasks. The final-release native Harbor oracle passes all 18
checks; each earlier release also passes its applicable checks.

Revision 1's Opus 5.5 high trial passed all three original releases in 15m12s.
After that genuine pass, the user authorized one harder revision and one
additional trial. Revision 2 adds reversible household identity as a fourth
release, rather than changing the grading of the original trial.
Revision 2 also genuinely passed all four releases in 18m46s.
**No substantive target-model failure was observed. This package does not meet
the assignment's central failure-evidence objective.**
Copilot CLI is the explicitly user-approved harness variation, not Claude Code.

## Idea and economic relevance

The fictional service maintains an account-classification analytics board in
SQLite. Orders and classification tags are corrected after import. Later
releases must retain unclassified orders, add rate-band fanout, and resolve
reversible household aliases without changing existing reports.
The durable deliverable is repaired projection
code, transactional auxiliary state, an acknowledged incident replay database,
regression checks and a handover.

This is a small analogue of incremental view maintenance in SaaS analytics,
reconciliation dashboards and embedded reporting systems. Rebuilding a shared
daily aggregate on every small correction scales with unrelated customer data;
silently changing bag/NULL semantics produces commercially misleading reports.
The task models those costs without needing customer data or a live warehouse.

## Design process and hypotheses

Previous workspace experiments showed that a longer feature checklist does not
by itself create a frontier-model failure. This task was designed from scratch
around semantic interactions and regression across releases instead. It does
not reuse their applications, data, graders, oracle code or benchmark instances.

Alternatives considered were bitemporal energy settlement, journal recovery,
and constrained maintenance planning. These would introduce substantial domain
rules or resemble existing workspace scenarios. The chosen SQL projection has
an independently executable semantic specification and a machine-independent
cost observable, making both correctness and fairness easier to audit.

Testable failure hypotheses:

* A competent developer might assume a small affected-account neighborhood
  permits recomputing its affected output groups. But 80,000 unrelated accounts
  share one group. An indexed account lookup is not an indexed global DISTINCT
  or extremum rebuild. The explicit work fixture distinguishes them.
* A developer might equate a missing tag with one actual NULL-valued tag.
  However, two such tag rows double join multiplicity; deletion of the last
  real tag restores one NULL-extended row in a left join. Transition checks
  distinguish value equivalence from support/multiplicity.
* Independently sensible order and dimension deltas need not compose when both
  sides change in one transaction. Coalesced before/final images and the final
  source query distinguish correct batch reasoning from intermediate-state
  assumptions.
* A later report can work while regressing previously released bag semantics,
  NULL grouping or durability. The environment and native conversation persist;
  the final verifier checks all active modes, not just the new feature.
* A developer might treat alias resolution as monotone union-find or assume
  distinct counts remain additive per account. But withdrawn aliases split
  components, dormant accounts can bridge active customers, and several
  members of a household can support the same output group. The new release
  requires per-group household support transitions, not numeric row
  deduplication or a global distinct-account substitution.

These are hypotheses about this task, not claims about model psychology.

## Long-horizon structure

1. Inspect the seeded day invalidator, host, schema and incident evidence;
   repair incremental `inner` reports under corrections and deletion.
2. Add `outer` without regressing existing behavior; handle changes in match
   support, duplicate classification rows and NULL groups.
3. Add `rated`, including multi-row band fanout and simultaneous corrections
   across all three sources, preserving rollback/retry/reopen behavior.
4. Add household-level distinct counts under link insertion, deletion, parallel
   edges, cycles and simultaneous source corrections. Preserve older raw-account
   counts and handle global connectivity through dormant identities.
5. Maintain acknowledged incident state across releases and demonstrate bounded
   update work against both shared groups and many unrelated groups.

The same source tree and incident database survive every step. The first prompt
does not diagnose the implementation; the public contract supplies the required
meaning, not the oracle algorithm. Future report definitions and the work bound
are available from the beginning, so later releases do not impose hidden rules.

## Environment and isolation

Harbor 0.24.0, Docker, two CPUs, 2 GiB memory and 4 GiB storage are declared.
Each agent release has 5,400 seconds; verification has 240 seconds.
The image combines digest-pinned official Python 3.12.12 and Node 22.14.0
Debian Bookworm images. Python's standard library and SQLite suffice for the
task and verifier. Node/git/curl are present for harness installation.

No package installation, random network call, credential or outside dataset is
needed by the application, tests or oracle. Image acquisition, the optional
Copilot npm installation and model inference need network/authentication.
Docker's Harbor backend in this installation does not support the requested
phase-level `no-network` override; the final metadata therefore accurately
declares `public` networking. Separate author oracle/control validation was
also run with Docker `--network none`.

Only `environment/app/` is copied into `/app`. The verifier, reference results,
oracle, author utilities and run evidence are not in the candidate image.
Harbor uploads its verifier only after a release and sanitizes shared verifier
directories before the next release.

## Verifier design

`tests/test.sh` delegates to a shared runner and writes
`/logs/verifier/reward.json`. Step-specific entrypoints select the active
release. Every runner starts by writing a zero reward, avoiding stale success
on infrastructure failure.

Expected report rows come from full independent SQLite GROUP BY queries over a
separate reference database. Household connectivity is rebuilt independently
with union-find over the reference link source, then joined into the full SQL
query. The oracle instead uses affected-component graph walks and persistent
support counters. Expected results do not use candidate auxiliary state or
candidate query generation. Grading compares typed values and complete row
multiplicity, ignoring row order and internal representation.

The suite checks:

* inserts, deletes, account/day/segment rekeys, duplicate bags, NULL grouping,
  zero versus NULL sums, distinct accounts and retractable extrema;
* left-join support transitions and chained rate fanout;
* alias-component merge/split, parallel-edge support, cycles, dormant bridges,
  per-group household membership, and corrections across all four sources;
* simultaneous source corrections, repeated writes to one source ID and
  reversed change-list order;
* 280 deterministic generated batches, including reopen checkpoints;
* populated-release upgrades, injected failure after the projection hook,
  rollback/retry, receipt idempotence and conflicting retries;
* both an 80,000-account shared group and 12,000 unrelated output groups;
* exact SQLite progress counting at one callback per VM instruction, bounded
  only during the documented small `apply` calls;
* protected host/input hashes, guarded hook writes/transactions, complete
  durable incident sources/receipts, and a further update after reopening a
  copy of the submitted incident database.

The final binary `overall` requires every applicable criterion. Category
fractions aid diagnosis; a good average cannot conceal one critical failure.
`multi_step_reward_strategy = "final"` is deliberate: the last verifier rechecks
all releases, and a repaired intermediate mistake is not an unrecoverable loss.
The handover's existence is required, but its wording is not judged.

### Verifier controls

Revision 1 classified all nine original controls correctly. Revision 2
classified all twelve original/household controls correctly. A subsequent
verifier-only legality audit added two more valid alternatives, for fourteen
total controls (three valid implementations and eleven faulty ones):

| Control | Expected | Observed |
|---|---|---|
| Reverse account processing; different valid JSON key encoding | Pass | Pass |
| Read-only SQLite schema/settings introspection | Pass | Pass |
| Evolve an auxiliary table during explicit bootstrap | Pass | Pass |
| Rebuild everything on each batch | Fail work only | Fail work only |
| Replace all-NULL sums with zero | Fail | Fail |
| Confuse joined-row count with distinct-account count | Fail | Fail |
| Ignore before images | Fail | Fail |
| Ignore rate-only corrections | Fail | Fail |
| Use NULL-safe rate join instead of SQL equality | Fail | Fail |
| Deduplicate duplicate source tags | Fail | Fail |
| Leave old account extrema/contributions behind | Fail | Fail |
| Count raw accounts instead of household support | Fail | Fail |
| Keep old alias components after a split | Fail | Fail |
| Ignore alias-only corrections | Fail | Fail |

See `evidence/controls/summary.json` and per-control assertion logs. Controls
receive a correct incident database first, then an independently tested faulty
implementation: a missing artifact is not used as a proxy for semantic failure.

## Oracle validation and rejected author errors

* The original seed fails its supplied classification-correction smoke check:
  the old `retail` result survives a `trade` correction.
* Author attempt 1 stopped before execution because this Docker backend does
  not implement phase-level network switching. This is not a model failure.
* Author attempt 2 exposed a verifier bug: its authorizer initially rejected
  SQLite's automatically named primary-key index on a valid auxiliary table.
  An exact denied-operation repro identified and fixed this before inference.
  This is not a model failure.
* Native Harbor oracle attempts 3 and 4 passed every active release. Attempt 4
  uses the final one-instruction counter and full candidate artifact capture.
* A clean extracted ZIP passed a further native Harbor oracle run in all
  three releases (`cohort-archive-oracle-01`); this used the same frozen
  runnable files as the source trial.
* The revision-2 offline direct oracle passed all 18 final checks. Its native
  four-release oracle (`cohort-v2-oracle-01`) also passed every category at
  every release, in 1m24s including environment and verification overhead.
* Revision 2 also passed all four releases from a clean extracted archive
  (`cohort-v2-archive-oracle-01`, 1m13s). All 32 frozen runnable files match
  the source-trial inputs.
* The valid alternative is revalidated with the same functional, durability
  and work requirements, including reversible household resolution.
* The final legality-corrected native oracle (`cohort-final-oracle-01`) passes
  every category at every release. Unchanged target submissions also pass
  independent replay under this final verifier at all four releases.
* The final verifier and packaged runnable files pass a further clean-archive
  native oracle (`cohort-final-archive-oracle-01`, 1m21s), including all
  18 final-release checks. Subsequent packaging only adds this run's evidence
  and updates this report; the 32 runnable-file hashes remain unchanged.

The oracle uses account-local contribution differences and indexed extrema;
the verifier instead recomputes complete SQL reports. This separation reduces
shared-algorithm false positives.

The revision-1 oracle's eight bounded operations used 36 to 1,680 SQLite
VM instructions each, against the public 300,000-instruction cap. This leaves
more than two orders of magnitude of implementation headroom; the cap is not
tuned to one coding style or machine speed. The full-rebuild control still
passed all functional/robustness checks and failed only the work requirements.
Revision 2's eleven bounded operations, including three reversible alias
changes, used 36 to 4,410 instructions, still over 60 times below the cap at
the most expensive operation.

## Target trial

| Revision | Job | Releases | Outcome | Elapsed |
|---|---|---:|---|---|
| 1 | `cohort-opus-01` | 3 | Genuine full pass | 15m12s |
| 2 | `cohort-v2-opus-01` | 4 | Genuine full pass | 18m46s |

The original trial's full pass, original input hashes, verifier and source
configuration are preserved under `evidence/cohort-opus-01` and
`evidence/revision-1`. It is not reclassified using the new requirements.
Revision 2's inference-time inputs are preserved separately in
`evidence/revision-2-inference/frozen-inputs.json`; the final package manifest
is `evidence/frozen-inputs.json`. The user authorized exactly one additional
trial for this revision, and that authorization is consumed. No additional
model trial or failure rate is implied.

### Fairness-only verifier correction after inference

An independent valid-solution probe found that the initial hook authorizer
rejected `PRAGMA table_info(orders)`. The contract prohibits changing host
pragmas, not reading schema information. It also allows auxiliary schema
evolution, which the original blanket ALTER restriction unnecessarily blocked.
Both restrictions were relaxed only for legal read-only introspection and
auxiliary-table changes. Source/transaction protections remain enforced.

This audit was not a target-model failure: the target already passed the
stricter original verifier at every release. No prompts, seed sources,
thresholds, reference semantics or correctness assertions were changed.
The original verifier and native rewards remain preserved. The final verifier
replayed all four captured target submissions **without changing their code or
databases**, and all categories remain 1.0. See
`evidence/cohort-v2-opus-01-final-verifier-replay/summary.json`.

### Result analysis

The proposed failure hypotheses did not expose a capability gap in either
authorized experiment. The model satisfied the bag/NULL semantics, regression,
reversible connectivity, durability and bounded-work requirements. Neither
trial ended in an infrastructure exception or agent timeout.

Accordingly, there is no legitimate wrong-hypothesis, skipped-verification or
state-tracking failure to report. Increasing semantic interactions from three
to four releases did not change the empirical result. This is a tested task
prototype with honest passing evidence, not a successful frontier-model-failure
submission. No grader condition was added after observing a model pass to turn
that pass into a failure.

The approved experiment uses Claude Opus 5.5, high reasoning, Harbor 0.24.0 and
Copilot CLI 1.0.102. An installation-only adapter uses the official pinned npm
package; model invocation, reasoning options, trajectory processing and native
resume behavior are inherited unchanged from Harbor's Copilot integration.
This is not the assignment's originally requested Claude Code harness.

## Reproduction

From a directory containing this task:

```sh
harbor run -p ./incremental-cohort-board -a oracle
harbor run -p ./incremental-cohort-board -a claude -m opus-5-5
harbor view ./jobs
```

The second command above is the assignment's requested spelling, not the
validated spelling for Harbor 0.24.0. This installed version calls the agent
`claude-code`; use a provider-valid model identifier and configured Anthropic
authentication, for example:

```sh
harbor run -p ./incremental-cohort-board -a claude-code \
  -m anthropic/claude-opus-5-5 --effort high --resume-trajectory
```

Native Claude Code execution is not claimed. Reproduce the actually approved
Copilot variation from the parent directory with valid Copilot authentication:

```sh
export PYTHONPATH="$PWD/incremental-cohort-board/author"
# Set COPILOT_GITHUB_TOKEN using your own authorized credential mechanism.
harbor run -p ./incremental-cohort-board \
  -a copilot_npm:NpmCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --resume-trajectory --agent-setup-timeout-multiplier 5
```

Author control reproduction:

```sh
docker build -t incremental-cohort-board:author \
  ./incremental-cohort-board/environment
python3 ./incremental-cohort-board/author/controls.py
python3 ./incremental-cohort-board/author/replay.py \
  ./incremental-cohort-board/evidence/cohort-v2-opus-01
```

The author freeze utility is not a reproduction prerequisite. Never overwrite
an inference-time manifest to retroactively change a trial's recorded inputs.
For the documented verifier-only fairness correction, the original manifest
was preserved separately before producing the final package manifest.

## Provenance, licenses and limitations

The task scenario, source application, schema, deterministic incident records,
prompts, oracle and tests were newly created for this exercise. No real customer
data, copied benchmark, public issue, CTF, tutorial instance or existing task
solution was used. The generic installation adapter follows Harbor's documented
subclass API; it is not task content. Harbor format and API references were
consulted at <https://docs.harborframework.com/tasks/overview>,
<https://docs.harborframework.com/tasks/configuration> and
<https://docs.harborframework.com/tasks/multi-step>.

External software is obtained through the declared images or harness:
Python (PSF License), SQLite (public domain), Node.js (MIT and bundled dependency
notices), Debian packages (their respective package licenses), Harbor
(Apache-2.0), and the optional GitHub Copilot CLI (its vendor terms). Upstream
notices remain in their distributions; no external dataset or source-code
corpus is copied into this task.

This is a deliberately bounded SQL/identity workload, not a general incremental SQL
engine. Text grouping is case-sensitive, accounts are non-NULL, and numeric
values are constrained to avoid overflow ambiguity. Aliases are undirected
equivalence edges, not probabilistic entity matching or legal household
definitions. High-fanout updates have
no locality cap; the small-neighborhood bound is explicitly public. One target
trial cannot establish a failure probability or generalize to native Claude
Code. A target pass must remain a pass.
