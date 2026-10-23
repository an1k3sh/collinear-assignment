# Recover the editable agreement

The procurement team has the published PDF of its facilities monitoring
agreement but has lost the editable Word file. Reconstruct it for the next
contract revision.

Read `/app/BRIEF.md` and reconstruct `/app/input/agreement.pdf` as
`/app/submission/agreement.docx`. Also deliver a reproducible script at
`/app/submission/rebuild.py` (and any local assets it needs) and a concise
`/app/submission/verification.md` describing what you checked and any limitations.

The Word document is the principal deliverable. Preserve the agreement's
meaning and visual organization while making its ordinary text, clauses and
tables genuinely editable. A PDF pasted into Word as page images is not a
reconstruction.

Python-docx, PyMuPDF, Pillow, LibreOffice Writer and Liberation/DejaVu fonts
are installed. You may inspect and render the PDF and your document, write
helpers and run local checks. No outside source data or conversion service
is needed. Preserve `/app/input` and `/app/BRIEF.md`.

Evaluation uses a fixed LLM document-quality rubric against the hidden
original Word source, not your conversation or tool-use trajectory. The
rubric, weights and acceptance thresholds are in the brief.
