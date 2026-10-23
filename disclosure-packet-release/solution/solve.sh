#!/bin/sh
set -eu
python /solution/release.py
cat > /app/submission/release-note.md <<'EOF'
# Public release

The packet was rewritten with the approved public substitutions in page text,
PDF string objects, metadata, bookmarks, annotations and all four attachment
payloads. Content streams were parsed rather than visually covered, including
text outside the displayed page area. The save rewrites the current object
graph rather than appending another revision containing private originals.

Supporting workbook XML was sanitized without changing numeric values,
formulas, worksheet structure or public audit content. The CSV, approval and
XML contact record retain their public fields. Attachment byte lengths and
checksums were updated. Financial rows, diagram, internal navigation and page
attachment associations remain intact.
EOF
