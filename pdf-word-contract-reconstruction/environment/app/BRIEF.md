# Editorial and acceptance brief

## Deliverable

Recreate the supplied fictional agreement as a useful editable DOCX. The PDF
is authoritative for all content, figures, labels, numerical values and
relationships. No external legal knowledge is required. Do not add terms.

Keep the same major sections, reading order, table relationships, captions,
headers/footers, footnote associations and signature fields. Preserve the
distinction between contractual text, explanatory notes and document furniture.
Retain visible clause numbers and cross-reference targets.

## Editability

Use real Word paragraphs and heading styles. Use automatic Word numbering
for the numbered clauses, real tables for schedules/pricing/signatures and
real footnotes for footnotes. Table headers should repeat if a table flows
to another page. Numbered clauses must remain renumberable; cross-reference
text must continue to identify the intended clause in the delivered version.
Live cross-reference fields are welcome but are not mandatory.

Keep figures as separate images or drawing objects with editable captions;
their internal artwork need not be editable. Do not turn entire pages,
paragraphs or tables into images. Avoid one text box per line or word: the
body must reflow when a paragraph grows. Working headings and tables matter
more than mimicking the original's private style names or XML.

## Visual fidelity

Preserve the hierarchy, columns, portrait/landscape orientation where used,
table groupings, major page/section breaks and figure proportions. Use
available fonts with similar metrics. Modest font, spacing or pagination
differences are acceptable. Exact pixels, line breaks, ZIP bytes, style IDs
and the original internal XML are not required.

No omitted text, incorrect amount, swapped table association, unreadable
glyph, material overlap or clipped row is acceptable. A small pagination
shift is preferable to clipping content to force an exact page count.

## Rebuild and check

`python /app/submission/rebuild.py` must recreate `agreement.docx` from the
PDF and any delivered local code/assets without network access. Keep any
generated intermediates outside `/app/submission`. Your script may contain
manually reconstructed text/layout; a general-purpose PDF converter is not
required. Do not merely store a finished DOCX under another name and copy it.

Check your rendered output and describe remaining limitations honestly.
After copying your document, the verifier extends one body clause and a
table description and renders the edited copy. It assesses whether these
ordinary edits still produce usable text and a table, not exact edited
pagination. These probes do not modify your submitted original.

## LLM grading

The judge is GPT-6.1 Sol (`gpt-6.1-sol`), high reasoning, through Copilot CLI
1.0.102. It receives reference/candidate page renders, extracted text and
Word structure, and edited-copy evidence. It does not receive the agent
trajectory or score the verification note's claims as proof.

The judge scores each dimension from 0 to 4:

* Content fidelity, 35%: words, numbers, symbols, conditions and associations.
* Editable structure, 30%: headings, paragraphs, numbering, tables, footnotes
  and edit/reflow behavior.
* Visual organization, 25%: layout, hierarchy, tables, figures and legibility.
* Navigation and document furniture, 10%: headings, clause references,
  headers/footers, captions and note placement.

Anchors: 4 = faithful and usable, only negligible differences; 3 = minor
localized defects without material loss; 2 = substantial repair needed;
1 = severe losses or largely unusable; 0 = absent or fundamentally wrong.
Each score must cite document evidence. The weighted score is divided by 4.
Acceptance requires at least 0.85 overall and at least 3 in every dimension.
A score of 3 means minor defects, not permission for an incorrect financial
amount or omitted contractual obligation.

Two independent judge calls use the same evidence and rubric. Scores are
averaged. A third call is made if the first two disagree on acceptance or
differ by at least two points in any dimension; the median per dimension
then determines the result. All calls and the disagreement are preserved.
Model/API/rendering errors are infrastructure errors, not candidate failures.

Basic artifact checks also require a readable DOCX, protected inputs,
required deliverables and a successful offline rebuild/render. A failure
claim must be backed by a concrete document defect, not by a score alone.
The rebuild has a 180-second limit in the provided four-CPU environment;
this is a reconstruction script, not a new agent run.
