# Verification note: agreement.docx reconstruction

## Rebuild
`python /app/submission/rebuild.py` uses python-docx and PyMuPDF to write `agreement.docx` in about 1 s and does not need network access. The script holds the reconstructed text and layout. It takes only the two figure bitmaps from `/app/input/agreement.pdf` at build time. It writes nothing else to `/app/submission`. `/app/input` and `BRIEF.md` were not modified.

## What was checked
- **Text:** I rendered the DOCX with LibreOffice 7.4 and compared the words in order with the source PDF. Both have 1,672 words and there are no differences. All amounts, dates, times, percentages and emails match.
- **Layout:** I compared each page side by side and matched the line baselines numerically. There are 8 pages and each page break falls in the same place as the original. Most lines are within about 1.5 pt of the original; a few are up to about 3 pt off.
  - Page 3 has two columns, starting after a continuous section break.
  - Page 5 (Schedule B) is a landscape section.
  - The header and footer are the same, with a live PAGE field.
- **Structure:**
  - **Styles:** headings use Title, Subtitle, Heading 1 (7) and Heading 2 (19).
  - **Clauses:** clauses 1–8 use one automatic Word numbered list (style "Clause"), which continues across the section breaks.
  - **Tables:** there are 12 real tables in the "Light Shading Accent 1" style. Every header row repeats on a new page and rows can't split across pages. In Schedule A, the Recurring and Summary category cells are vertically merged.
  - **Footnote:** the charge-rules footnote is a real Word footnote (`footnotes.xml`).
  - **Figures:** each figure is an inline picture. Its title is an editable heading with a SEQ Figure field, and its note uses the Caption style.
- **Cross-references:**
  - "clause 8" (in clause 1 and in Execution) is a REF field to a bookmark on clause 8.
  - The page numbers in the cover's Navigation paragraph are PAGEREF fields to bookmarks on each heading.
  - "Appendix E" and "Schedule B" are internal hyperlinks.
- **Editing test:** I lengthened clause 2 and two table cells (Definitions and Schedule B) in a copy and rendered it. The text and table rows reflowed with no overlap or clipping, and it stayed at 8 pages.

## Limitations
- I could only render with LibreOffice; I couldn't check the file in Microsoft Word. Headings use DejaVu Sans and body text uses Liberation Sans, which are the fonts in the source PDF. Where those fonts aren't installed, Word will substitute others and line breaks may change.
- The values shown by the REF and PAGEREF fields are stored in the file. Word shows those stored values until the fields are updated (F9). After clauses are renumbered, the REF field shows the clause's new number.
- The two figures are bitmaps taken from the PDF, so the artwork inside them can't be edited; their captions can.
- Paragraph and table spacing were adjusted by eye to match the PDF. The original style names and XML are not reproduced. In the footnote, the reference number is superscript, where the PDF shows it inline.
