# Public release note — disclosure packet

`release.pdf` is the public copy of the financial statement packet. Every
private identifier in the release map was replaced with its public value
(`CLIENT-07`, `EMAIL-REMOVED`, `ACCOUNT-REMOVED`, `PUBLIC-CASE-071`) or was
removed where it served no public purpose.

## What changed

- **Page 1:** the customer, email, account and legacy-case lines now show
  their public replacements. They use the same font and position as before.
  The rest of the page, including the financial table, is unchanged.
- **Page 2:** an invisible text run placed off the page held private
  identifiers. It was removed. The visible page is unchanged.
- **Annotations:** the page 2 audit note keeps its public content (net
  1387.40 USD, approval APPROVAL-2026-118). Its author, subject and the
  contact name in its text use the public mapping. The two paperclip
  attachments on page 3 keep their annotations and file associations, and
  their author, subject and description labels were mapped too.
- **Bookmarks:** all three bookmarks are kept in their original order and
  point to their original pages. The first title was mapped.
- **Document metadata:** author, subject and keywords were removed from the
  document properties, along with the XMP metadata stream. The title was
  mapped.
- **Attachments:** each file keeps its original filename. The payloads were
  rewritten, and their size and checksum values were updated to match.
  - `statement.xlsx`: both worksheets, all row labels, amounts and formulas
    (`SUM`, `ROUND`, total) are kept. The cached results are correct. The
    shared strings, the `ClientLabel` defined name, the header and footer,
    and the cell comment were mapped. The creator, last-modified-by and
    description properties were cleared.
  - `transactions.csv`: the columns, row order, transaction IDs (TX-8471,
    TX-9920) and amounts are unchanged. The customer, email and account
    fields were mapped.
  - `approval.txt`: the approval reference, decision and amount (1498.39 USD)
    are unchanged. The customer, contact and case fields were mapped.
  - `contact-card.xml`: the element structure, public case reference and
    release authorization are unchanged. The name, email and account values
    were mapped.
- **File structure:** the PDF was written as a single new revision with no
  incremental updates. Objects that no longer had any references, such as
  the old payloads, the old text and the old metadata, were not written out.

## Verification performed

1. **Leak scan.** I searched the released file for every mapped private value
   and for fragments of those values. The scan covered the raw PDF bytes,
   every decoded stream, every object dictionary and the trailer. It
   included hex, UTF-16 and inflated-blob forms, and every part inside the
   attached workbook. There were no matches. The same scan run on the source
   packet finds them.
2. **Text comparison.** I compared the extracted text of each page with the
   source. The only differences are the four mapped lines on page 1. All
   amounts (1200.00, 347.40, -160.00, 1387.40, 110.99, 1498.39) and the
   public IDs remain searchable text.
3. **Rendering comparison.** I rendered each page without annotations and
   compared it with the source. Pages 2 and 3, which include the diagram,
   are pixel-identical. On page 1 the only differences fall inside the
   private-field block, so the table is unchanged.
4. **Navigation and attachments.** The PDF has three pages at 612×792. The
   three bookmarks point to pages 1, 2 and 3. The page 1 link still goes to
   page 3. Both document-level attachments and both page 3 file-attachment
   annotations open and return the cleaned content.
5. **Workbook checks.** openpyxl reads the workbook and shows the formulas
   intact and the cached totals correct. LibreOffice Calc recalculates it
   correctly: changing the Services amount to 2200 gives a net of 2387.40, a
   tax of 190.99 and a total of 2578.39.
