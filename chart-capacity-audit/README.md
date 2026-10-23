# Chart-only capacity audit

One original Harbor task about visual evidence extraction, cross-chart
reasoning and reproducible decisions. The agent receives four PNG dashboard
exports, an offline HTML viewer, a precise capacity policy and a flawed draft
memo. It must recover observations, write a reusable analysis program, audit
the claims and recommend an allocation with an uncertainty certificate.

This is a chart-as-input task, not a chart-rendering or aesthetic evaluation.
It does not use an LLM judge. A plausible paragraph cannot replace a correct,
reproducible calculation.

Measured result: Opus 5.5 high on Copilot CLI 1.0.102 passed every component
with verified native image access. This task did not demonstrate a model
failure; see the run report and preserved trial evidence.

## Inspect

* [Task prompt](instruction.md)
* [Local chart viewer](environment/app/report/index.html)
* [Policy](environment/app/policy.md)
* [Deliverable schemas and scoring](environment/app/deliverables.md)
* [Run report](RUN_REPORT.md)

The task image contains only `environment/app/`. Author data and renderer,
verifier ground truth, oracle observations and evidence are NOT included in
the image. The HTML has only image references and generic captions; the PNGs
contain pixels without source-data metadata. The original data can be known
to the verifier without being available to the agent.

## Image-access prerequisite

The trial agent must be able to SEE the PNGs using native image viewing or a
browser tool. Starting an HTTP server alone does not give a text-only agent
visual access. The task does not bundle a browser MCP server or assume a
particular vendor's image tool.

Before interpreting a model trial, inspect its tool availability and confirm
in the trajectory that images reached the model. The author visually inspected
all four PNGs and tested the HTML viewer in the VS Code browser. That does NOT
certify image access in every Harbor agent adapter.

If image access is missing, classify the trial as an infrastructure/capability
configuration failure, not chart-reasoning evidence. Supplying full extracted
values as a fallback would change what the benchmark measures.

## Reproduce

Docker and Harbor 0.24.0:

```sh
uvx --from harbor==0.24.0 harbor run -p ./chart-capacity-audit -a oracle
uvx --from harbor==0.24.0 harbor run -p ./chart-capacity-audit -a claude -m opus-5-5
uvx --from harbor==0.24.0 harbor view ./jobs
```

These assume the current directory contains the task. In the development
workspace use `-p ./collinear-candidate/chart-capacity-audit`.
The model command is the assignment's requested spelling; verify provider
model availability, reasoning effort and image-tool support in the actual
harness configuration. The completed trial used the Copilot adapter below,
not Claude Code.

The previous experiments used this alternative adapter:

```sh
GH_TOKEN="$(gh auth token)" uvx --from harbor==0.24.0 harbor run \
  -p ./chart-capacity-audit -a copilot-cli -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102
```

The same image-access preflight applies. Do not put credentials in task files.
Installation/inference may need network; image viewing, analysis and verification
need no external network. The pinned image uses Python's standard library and
checked-in PNGs: no task dependency installation is needed.

Author validation, from the task directory:

```sh
docker build -t chart-capacity-audit:author environment
mkdir -p local-evidence
docker run --rm --network none \
  -v "$PWD:/submission:ro" -v "$PWD/local-evidence:/evidence" \
  chart-capacity-audit:author \
  python /submission/tests/author_check.py /evidence
docker run --rm --network none -v "$PWD:/submission:ro" \
  chart-capacity-audit:author \
  python -m unittest discover -s /submission/tests -p test_grader.py -v
```

To regenerate charts deliberately, use an isolated Python 3.12 environment,
install `author/requirements.txt`, then run `python author/render.py`.
That author-only command writes the PNGs and private truth. The distributed
PNGs are the canonical evidence; font/platform differences in regeneration
must be visually reviewed and protected hashes refreshed before a new version.
Do not regenerate a task during a model trial.

## Why this is economically useful

Capacity decisions often rely on exported dashboard reports when underlying
data is inaccessible. Confusing percentage with absolute demand, averaging
unequal denominators, or treating missing telemetry as zero can misallocate
budget. This task requires a traceable correction, not an attractive chart
or an unsupported recommendation.

The benefit coefficients are explicitly supplied planning assumptions. This
task does not claim that adding servers causally reduces failures by those
amounts. That avoids an underspecified systems-diagnosis problem.

## Provenance and novelty

The scenario, dataset, chart design, memo, policy, analysis interfaces,
reference calculator, oracle and tests were created from scratch for this
exercise. No public benchmark, issue, chart dataset or external image was
copied. Matplotlib with its bundled DejaVu font rendered the original data;
author rendering dependencies retain their upstream licenses. All values are
synthetic and contain no private operational information.

The earlier SQLite experiments are not included in this submission and are
not evidence of this task's difficulty.
