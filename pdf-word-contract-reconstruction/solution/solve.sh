#!/bin/sh
set -eu
mkdir -p /app/submission
cp /solution/rebuild.py /app/submission/rebuild.py
python /app/submission/rebuild.py
cat > /app/submission/verification.md <<'EOF'
# Reconstruction verification

The supplied script constructs the editable agreement using paragraphs, heading
styles, native tables, automatic clause numbering and a real footnote. Figures
are separate image objects with editable captions. The script is deterministic
in content and runs without network access.

The authored reference has eight pages, with Schedule B in landscape and
operational responsibilities in two columns. Financial values, clause numbering,
service-window associations and the billing footnote have been checked during
author validation. The verifier renders the DOCX and two normal edits.
EOF
