# Release the warehouse reslotting plan

Operations wants to reduce walking in the current pick layout without exceeding
the weekend relocation authorization. Produce a complete assignment using
the records in `/app/data` and the contract in `/app/POLICY.md`.

Deliver `/app/submission/layout.json`, a reproducible search/analysis program
with its execution command in `/app/submission/REPORT.md`, and the report
itself. The layout must meet every placement and labor constraint and the
travel target in `data/settings.json`. A globally optimal or unique assignment
is not required.

The public scorer is available:

```sh
python /app/tools/evaluate.py --data /app/data --layout /app/submission/layout.json
```

Use it to verify the actual saved artifact. Do not change `/app/data`,
`/app/POLICY.md` or `/app/tools`. You may use Python, NumPy and the installed
C++ compiler. No external service, dataset or network is required.
