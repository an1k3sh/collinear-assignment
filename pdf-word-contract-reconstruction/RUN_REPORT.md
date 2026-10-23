# pdf-word-contract-reconstruction: run report

## Target-model record and failure analysis

| Job | Harness / requested model | Recorded overall | Interpretation |
|---|---|---:|---|
| `pdf-word-opus-01` | `prototype_harness:PrototypeCopilot` / `claude-opus-5.5` | 1.0 | Recorded pass |

Historical trials used Copilot CLI, not Claude Code. Passes and documented infrastructure, contract or verifier errors are not evidence of a substantive model failure.

## Reproduction from the collection directory

```sh
harbor run -p ./pdf-word-contract-reconstruction -a oracle
harbor run -p ./pdf-word-contract-reconstruction -a claude -m opus-5-5
harbor view ./jobs
```

The illustrative `claude` alias is provider/version dependent. Harbor 0.24.0 exposes `claude-code` for the native Claude Code harness; supply the actual available model ID, credentials and high reasoning configuration. See the detailed experiment commands below for the measured harness, rather than relabeling historical results.

For the LLM verifier, export `DOCX_JUDGE_TOKEN` on the host from an entitled Copilot account before the oracle or model run. It resolves only at verifier execution. Judge model: GPT-6.1 Sol high. This verifier requires network and incurs model usage.

## Checklist and fairness audit

* The task prompt states input locations, protected boundaries and durable deliverables. Only environment sources are copied into the agent image; reference solutions and tests are staged by Harbor separately.
* Metadata declares category, timeouts, resources and network policy. `public` network permits harness setup/inference; it is not an enforced offline sandbox.
* The Dockerfile pins the base image and declares dependencies. Validation uses fresh Docker containers on macOS Docker Desktop (Linux arm64); other architectures are not certified.
* Both shell entrypoints are executable. The verifier emits reward JSON or text under `/logs/verifier` on graded outcomes. Infrastructure errors must not be interpreted as model defects.
* Functional checks and existing alternate/mutation controls test the task's stated outcomes. A fresh untouched/no-op baseline is checked during collection validation; detailed verifier design and limitations follow below.
* Economic usefulness, long-horizon subgoals and provenance are recorded in the detailed notes. [LICENSES.md](LICENSES.md) inventories external tools and license sources.
* Versioned tasks reuse same-exercise work openly. They are not independent originality claims and are not ports of unrelated existing benchmarks.

## Detailed design and historical experiment notes

# Run report: PDF to editable Word

## Outcome

The benchmark was created and tested end to end. **The oracle and the first
Opus 5.5 high reconstruction both pass.** This is not evidence of a substantive
frontier-model failure.

The task follows the requested direction: author a Word document, export it
to PDF, give the PDF to the solver, and grade the reconstructed Word document
with an LLM against the hidden original.

## Source and deliverables

The [original DOCX](tests/reference/original.docx) is an eight-page fictional
facilities-monitoring agreement. Its [PDF export](environment/app/input/agreement.pdf)
is the solver input. The original DOCX is only in the verifier/reference
directory, not in the agent image.

The source has two-column prose, eight automatically numbered clauses,
12 native tables, merged pricing cells, a true billing footnote, a landscape
response-time schedule, two figures, headers/footers and blank signature forms.
It was generated using python-docx/OOXML and exported using the pinned
LibreOffice environment, not a licensed Microsoft Word installation.

The solver must deliver the reconstructed DOCX, its rebuild script and a
verification note. The original authoring script also serves as a
constructive known-solution oracle. It creates the source content and
structure; the oracle does not merely copy the reference DOCX.

## Judge and pretrial calibration

Judge: **GPT-6.1 Sol (`gpt-6.1-sol`), high reasoning, Copilot CLI 1.0.102**.
This exact model and reasoning level were approved before judging.

The judge sees rendered reference/candidate page pairs, independently
extracted Word structure/text and ordinary edit probes. It never sees the
solver trajectory. It has only a read-only view tool, and actual image-view
events are checked. Every score needs concrete document evidence.

Two independent sessions grade each artifact. A third is required for
acceptance disagreement or a two-point discrepancy in a dimension. No third
session was necessary in the six calibration cases or the solver trial.

| Case | Content | Editability | Visual | Navigation | Weighted | Accepted |
|---|---:|---:|---:|---:|---:|---|
| Original DOCX | 4 | 4 | 4 | 4 | 1.000 | Yes |
| Equivalent style-based numbering | 4 | 4 | 4 | 4 | 1.000 | Yes |
| Wrong tax-inclusive total | 2 | 4 | 4 | 4 | 0.825 | No |
| Wrong site attendance target | 2 | 4 | 4 | 4 | 0.825 | No |
| Word document containing page images | 4 | 0 | 4 | 2 | 0.650 | No |
| Missing billing footnote | 2 | 2 | 4 | 3 | 0.650 | No |

Acceptance is weighted quality >= 0.85 with every dimension >= 3.
The weights are content 35%, editability 30%, visual 25%, navigation 10%.
The full [public rubric](environment/app/BRIEF.md) and
[judge prompt](tests/judge_prompt.txt) were fixed before the target-model run.
All eight local judge-contract unit tests also pass.

## Native Harbor runs

| Run | Harness | Outcome |
|---|---|---|
| `pdf-word-oracle-01` | Native Harbor oracle | All criteria 1.0 |
| `pdf-word-oracle-final` | Native Harbor oracle, final pretrial files | All criteria 1.0 |
| `pdf-word-opus-01` | Copilot CLI 1.0.102, Opus 5.5 high | All criteria 1.0 |

Target trial ID: `pdf-word-contract-reconstruction__jvNuZDc`.

The target run started at 2026-10-23 19:09:07 UTC and finished at
19:22:52 UTC, about **13 minutes 44 seconds** end to end.
Agent execution took about **10 minutes 28 seconds**. There was no timeout
or harness exception.

Both independent judge sessions assigned:

| Dimension | Review 1 | Review 2 |
|---|---:|---:|
| Content fidelity | 4 | 4 |
| Editable structure | 4 | 4 |
| Visual organization | 4 | 4 |
| Navigation and furniture | 4 | 4 |

The grader confirmed an eight-page editable reconstruction, correct financial
values and site-specific targets, automatic clauses, a linked footnote,
native tables, two-column prose and the landscape schedule. It also found
that the body-clause and table-description edit probes reflowed without
material loss or clipping.

The model additionally created live clause/page references. This was beyond
the minimum contract, which allowed correct static cross-reference text.
Its note explicitly disclosed that only LibreOffice rendering was tested.
The evaluator did not treat that self-report as evidence: it inspected the
artifact separately.

Author inspection of the charges and landscape-schedule comparisons supports
the judges' observations. The output is not a page-image shortcut. No
material defect has been independently established.

## Preserved evidence and freeze

[Model evidence](evidence/model/) includes the native result/config,
trajectory, submitted DOCX/script/note, verification output, both judge
responses, comparison renders, structural evidence and judge event logs.
[Calibration evidence](evidence/calibration-summary.json) records the
positive and negative cases.

All 21 frozen task files matched their pretrial SHA-256 hashes after the
model finished. Documentation and evidence were then updated to report the
observed pass. The input, oracle, rubric and grader were not adjusted to
change this model's score.

Copilot CLI is **not Claude Code**. No Claude Code trial has been run.
The Claude Code command in the README is a reproduction recipe, not a
description of the measured experiment.

## Limitations and honest interpretation

* LLM scores are stochastic judgments, not mathematical proofs.
* Six calibration cases do not establish a comprehensive error rate.
* The backend behind a model name may change; preserve the raw evidence.
* The renderer is LibreOffice, so Word-specific rendering differences remain
  untested.
* The benchmark evaluates faithful reconstruction of one original document,
  not a universal PDF-to-DOCX converter.
* A single passing solver trial says nothing reliable about harder document
  families or a general success rate.
* Standard Harbor execution is not a hardened sandbox against deliberately
  malicious candidate code. Do not use production credentials or sensitive
  documents for benchmark runs.

The result is a working, calibrated benchmark and a clean passing baseline.
It must not be relabeled as a failure merely because the original research
goal was to find one.

Reproduction commands and external authentication/network requirements are
in [README.md](README.md).
