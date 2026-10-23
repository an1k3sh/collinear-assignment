# Prepare the public disclosure packet

Prepare a public-release copy of `/app/input/packet.pdf` under the rules in
`/app/POLICY.md`. The private-to-public identifier mapping is in
`/app/input/release-map.json`.

Deliver only `/app/submission/release.pdf` and
`/app/submission/release-note.md`. Treat everything in the submission directory
as public. Keep private working scripts, extracted originals and intermediate
files elsewhere.

The released packet must remove the specified private identifiers while keeping
the public financial content, document navigation and supporting attachments
usable. Audit the whole packet before publishing; a visually plausible page
is not sufficient evidence of a correct release.

PyMuPDF, pikepdf, openpyxl and LibreOffice Calc are installed. No network,
external service or new source data is needed. Preserve `/app/input` and
`/app/POLICY.md`.
