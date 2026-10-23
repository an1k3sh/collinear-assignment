# Public release policy

## Privacy boundary

All records in this exercise are fictional, but process them as a real client
disclosure. Every `private` value in `input/release-map.json` must be removed
from the complete released package and replaced with its corresponding
`public` value where it is needed for readable content or a retained field.

The release consists of the PDF, every attachment available through it, and
the release note. Private values must not remain recoverable as hidden text,
annotations, document properties, metadata, navigation titles, spreadsheet
metadata, unused objects, or prior saved revisions. Deleting a visible field,
placing a covering rectangle, or changing only its displayed appearance is
not enough. Remove obsolete private payloads as well as current ones.

All map values are literal case-sensitive text; there is no inferred PII
classification requirement. The complete list is authoritative. Preserve
unrelated public identifiers and amounts, even when they share a short number
substring with a private identifier. Public replacements are not confidential.

## Preserve the released document's utility

Keep all three PDF pages, their order, size, public text and financial rows.
Keep the original public content searchable/selectable; do not flatten whole
pages into screenshots. Preserve the financial table and the public diagram
with no material visual change. Local replacement text may use a different
font so long as it remains legible and stays in the original private-field
area. The page's public values must not be shifted, removed or overlaid.

Retain the three section bookmarks in order and with their original page
destinations; apply public replacements to their titles. Preserve the internal
link on page 1 to the supporting-material page. Keep all public audit note
content on its original page; sanitize private text within notes rather than
deleting all annotations.

All four supporting files must remain accessible by their existing filenames.
Two are document-level attachments:

* `statement.xlsx`
* `transactions.csv`

Two are attachments associated with the paperclip annotations on page 3:

* `approval.txt`
* `contact-card.xml`

Retain the page-associated attachment annotations and their associations.
Do not turn these into inert icons or replace their payloads with unrelated
blank files. Descriptive labels and attachment metadata are part of the
privacy boundary too.

## Supporting-file content

`statement.xlsx`:

* Retain every worksheet, all public row labels and numeric input values.
* Retain working formulas for the statement totals; the workbook must still
  recalculate when an amount changes.
* Save correct cached formula results so read-only preview consumers also see
  the released totals.
* Retain public annotation/comment content, but apply the release mapping to
  private portions wherever they occur.
* Metadata, defined names, headers/footers, caches and other workbook parts
  must not retain the mapped private text.
* The original worksheet names are public and need not be changed.

`transactions.csv`: preserve column names, row order, public identifiers and
all numeric values. Apply the release mapping to customer-related field text.

`approval.txt`: retain its approval reference, decision and amount, applying
the release mapping to private fields.

`contact-card.xml`: retain its element structure, public case reference and
release authorization; replace mapped customer values.

The PDF does not need to preserve exact object numbers, compression, producers,
timestamps or binary bytes. Metadata can be cleared where it has no public
utility; mapped fields in the visible content and retained supporting records
must still contain their public replacements.

The release note is public: explain your verification without repeating
private source identifiers. No particular wording or redaction library is
required. The verifier checks the actual PDF, its reachable and residual
payloads, supporting files, financial values, navigation and recalculation.
