# Financial disclosure packet release

An original document-production task: publish a client-safe financial packet
without destroying its useful records. The input contains three PDF pages,
two document attachments, two page-associated attachments, a calculated
workbook, an audit note, bookmarks and an internal link.

## Why this is a real, linked workflow

Disclosure teams must inspect the package, establish the privacy boundary,
transform multiple document formats, preserve public financial information,
maintain working attachments and audit the final release. Visual redaction
alone does not establish that a file is safe to distribute. Losing formulas,
supporting evidence or navigation also makes a release operationally unusable.

The source data, client names and account identifiers are entirely fictional.
The top-level assignment specifies the deliverables without diagnosing the
source's individual defects. The public policy states the complete privacy
and preservation requirements; it does not require guessing what is private.

## Verification and fairness

The verifier checks seven criteria: protected inputs, release contents,
privacy, public document content, navigation/attachment associations,
supporting records and actual spreadsheet recalculation. Overall is the
conjunction. No LLM judge, trajectory grading or required implementation is used.

Privacy checks inspect decoded PDF objects, page text beyond normal page
bounds, annotation properties, prior incremental revisions, embedded files,
workbook ZIP members and the public note. Public searchable text and aliases
are checked separately. Public visual regions use tolerant image differences,
not exact PDF bytes. CSV/XML/workbook content is inspected semantically.
LibreOffice is used to change a numeric input and verify recalculated totals.

Two valid releases (including a linearized/uncompressed alternative) and ten
fault controls are classified correctly. Controls include private metadata,
off-page text, page-associated files, workbook properties, old revisions,
missing attachments, a removed chart and cached-but-fixed totals. See
[control results](evidence/control-validation.json).

The oracle traverses the actual PDF object graph, rewrites content streams,
sanitizes nested attachments, preserves formulas/caches and saves a full new
file. Native Harbor oracle validation passes all seven criteria. An initial
oracle missed file streams without an explicit EmbeddedFile type; it was
corrected before any model trial. A pretrial verifier control also caught
the difference between a linearized PDF's provisional trailer and a genuine
prior revision. Neither author-side error is model-failure evidence.

## Reproduction

From the parent directory:

```sh
harbor run -p ./disclosure-packet-release -a oracle
harbor run -p ./disclosure-packet-release -a claude -m opus-5-5
harbor view ./jobs
```

The Claude Code command is the assignment's requested recipe. The authorized
experiment uses **Copilot CLI**, not Claude Code:

```sh
export PYTHONPATH="$PWD/disclosure-packet-release/author"
# Supply valid Copilot authentication in the local environment.
uvx --from harbor==0.24.0 harbor run -p ./disclosure-packet-release \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

The adapter changes installation only: official checksum-verified Node
22.14.0 and pinned official Copilot CLI 1.0.102. Harbor execution and trajectory
handling remain inherited unchanged. Dependencies and inference require
network access; solving and verifying the task are offline.

To regenerate the authored seed packet (not needed to run the task), mount
this directory at `/task` in its environment image and run
`python /task/author/generate.py`. Regeneration can change PDF/ZIP timestamps,
so refresh the protected input hashes before author-side revalidation.
Controls accept the path to a passing oracle's released PDF:
`python /task/author/validate_controls.py /path/to/release.pdf`.

## Provenance and limitations

All seed documents, values, policies, generation code, oracle and checks were
created from scratch for this exercise. No existing benchmark or public issue
was ported. PyMuPDF, pikepdf, openpyxl, Pillow and LibreOffice are the declared
external tools. Python is digest-pinned and Debian packages come from a frozen
snapshot; Python dependencies are version-pinned.

This is a finite literal-mapping release, not general PII detection or a
production PDF sanitizer certification. It does not test arbitrary malicious
PDF encodings, OCR of unrelated images, digital signatures, encrypted PDFs
or macros. PyMuPDF 1.26.3's document-level attachment-update convenience API
has a buffer-wrapper defect; direct object updates or delete/re-add operations
work. No required task operation depends on that API. Failures attributable
only to that library defect would not be treated as substantive evidence.

The task permits two hours; the oracle and verifier each finish in seconds.
Model results, when available, are recorded separately in the evidence.
