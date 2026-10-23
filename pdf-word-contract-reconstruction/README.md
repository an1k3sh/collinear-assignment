# PDF to editable Word: procurement agreement reconstruction

## What was created

An eight-page fictional procurement agreement was authored as a real Word
document, then exported to PDF. The solver receives only the PDF and the
public editorial brief. It must reconstruct an editable DOCX and a repeatable
local build script.

The original includes automatic clauses, two-column responsibilities, merged
pricing cells, a billing footnote, a landscape service-window matrix,
separate figures with editable captions, repeating table headers and
signature forms. The economic use is recovering a lost editable contract
source for the next revision, not producing an image-only facsimile.

This is a DOCX artifact task, not an Office.js task. No licensed Word host is
required. LibreOffice Writer is the pinned evaluation renderer; Microsoft
Word itself has not been used to certify cross-renderer pagination.

## LLM grading

The judge is **GPT-6.1 Sol (`gpt-6.1-sol`), high reasoning**, through official
Copilot CLI 1.0.102. This exact model was confirmed in the authenticated model
catalogue and approved before use.

It assesses the final document, never the solver trajectory. Verifier-generated
evidence includes side-by-side rendered page images, document/table text,
paragraph styles, numbering definitions, footnotes, section geometry,
headers/footers, and renders after two ordinary edits. The judge has only
the read-only `view` tool; it must inspect every required comparison image.
Its actual tool events are checked, rather than trusting a claimed checklist.
Candidate text is explicitly untrusted and cannot change the rubric.

Native PDF attachment transport did not provide usable visual input in the
pinned CLI. A smoke test caught this before calibration. The working design
renders PNG comparisons and checks actual image-view calls. A separate image
smoke test correctly read the figure values.

Scores are 0-4 for content (35%), editable structure (30%), visual organization
(25%) and navigation/furniture (10%). Acceptance requires weighted quality
at least 0.85 and every dimension at least 3. The complete public anchors and
material-defect rules are in [the brief](environment/app/BRIEF.md).

Two independent sessions judge each artifact. Their scores are averaged;
acceptance disagreement or a two-point dimension difference triggers a third
session and per-dimension medians. No favorable rerun selection is allowed.
Evidence, individual scores, rubric hash, model identity and disagreements
are saved. Provider, malformed judge-response and rendering infrastructure
errors do not produce a success or a candidate-failure score.

Programmatic gates check readable/rebuildable deliverables and protected
inputs. They do not replace the LLM quality assessment. The rebuild comparison
ignores DOCX timestamps/ZIP bytes and checks rendered content and table structure.

## Calibration and solvability

**Measured target-model result:** Opus 5.5 high passed the first frozen trial,
with both GPT-6.1 Sol high reviews assigning 4/4 in all four dimensions.
This benchmark has **not** demonstrated a frontier-model failure. See the
[run report](RUN_REPORT.md) for timings, artifacts and limitations.

Before a solver trial, the judge correctly classified:

| Control | Expected | Weighted quality |
|---|---|---:|
| Exact original | Accept | 1.000 |
| Equivalent style-based numbering, slightly changed heading size | Accept | 1.000 |
| Incorrect total, 45,960.00 instead of 45,360.00 | Reject | 0.825 |
| Wrong Eastbank attendance target, 120 instead of 60 minutes | Reject | 0.825 |
| Page images in a DOCX | Reject | 0.650 |
| Missing billing footnote | Reject | 0.650 |

All six cases received two reviews; none had an acceptance disagreement.
This is measured calibration, not proof that the LLM judge has no errors.
See [calibration summary](evidence/calibration-summary.json).

The native Harbor oracle passes with 1.0 on every dimension. Its rebuild script
constructs the document from authored text and layout, rather than copying a
hidden finished DOCX into the submission. This is a known-solution oracle,
not a claim that a general-purpose PDF converter solves arbitrary inputs.
The judge reference is independent of the candidate's self-report, but the
oracle naturally shares the original document's authoring specification.

## Reproduction

Requires Docker, network access for pinned dependencies and model calls, and
a Copilot account entitled to GPT-6.1 Sol. No credentials are packaged. Set
`DOCX_JUDGE_TOKEN` in the host environment. Harbor resolves its placeholder
only for the verifier; do not put the token in task files or command arguments.
For an already authenticated GitHub CLI:

```sh
export DOCX_JUDGE_TOKEN="$(gh auth token)"
```

From the directory containing this task:

```sh
harbor run -p ./pdf-word-contract-reconstruction -a oracle
harbor run -p ./pdf-word-contract-reconstruction -a claude -m opus-5-5
harbor view ./jobs
```

Use Harbor 0.24.0 for the validated implementation, for example
`uvx --from harbor==0.24.0 harbor run -y ...`. `-y` confirms the declared
verifier credential environment prompt noninteractively.

The Claude Code command above is the assignment recipe, **not evidence that a
Claude Code trial was run**. The locally authorized target-model experiment
uses Copilot CLI:

```sh
export PYTHONPATH="$PWD/pdf-word-contract-reconstruction/author"
export GH_TOKEN="$(gh auth token)"
uvx --from harbor==0.24.0 harbor run -y \
  -p ./pdf-word-contract-reconstruction \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

The adapter changes only installation; native Harbor Copilot execution and
trajectory handling are inherited unchanged.

Author tools:

```sh
docker build -t pdf-word-author:local pdf-word-contract-reconstruction/environment
docker run --rm -v "$PWD/pdf-word-contract-reconstruction:/task" \
  pdf-word-author:local python /task/author/generate.py --author
docker run --rm -v "$PWD/pdf-word-contract-reconstruction:/task" \
  pdf-word-author:local python /task/author/make_controls.py
```

Generation updates the hidden original and public PDF; refresh protected hashes
and rerun calibration before freezing a new revision. Do not regenerate during
an active model trial. To judge a control, run `tests/judge.py REFERENCE.docx
CANDIDATE.docx OUTPUT_DIRECTORY` in the image with `GH_TOKEN` supplied via
the container environment, not embedded in an image.

## Provenance, fairness and limitations

All document text, pricing, schedules, figures, forms, code and rubric were
created for this exercise. There is no real customer information or copied
benchmark task. Third-party tools are version-pinned; Python uses an image
digest and Debian packages use a dated snapshot. Dependencies retain their
upstream licenses, including PyMuPDF's AGPL/commercial licensing.

The original was exported with LibreOffice rather than Microsoft Word.
Scoring allows reasonable font/spacing/pagination variation, and explicitly
accepts different equivalent DOCX structures. Ordinary prose, clauses and
tables must remain editable. Whole-page images are a substantive failure even
when they look accurate.

The model service cannot be frozen by image digest: availability, backend
revisions and stochastic judgments remain external dependencies. Scores may
vary despite a fixed model ID and rubric. Repeated independent review and
calibration reduce but do not eliminate that limitation. There is no claim
of a statistically established failure rate from a single solver trial.

Judge calls process only the fictional documents and extracted document
structure. Review logs are retained for audit. Any reported solver failure
must also be independently tied to a real artifact defect, not merely an
LLM's numerical opinion.
