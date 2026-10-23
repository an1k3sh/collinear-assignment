# Refresh interface and workbook contract

CLI (run from /workspace):

```
python refresh.py --source inputs/source.xlsx --as-of YYYY-MM-DD \
  --output output/settlement.xlsx [--previous output/archive/close-N.xlsx]
```

The script must exit nonzero and explain invalid input or failed recalculation.
Inputs are read-only. Create output parent directories if necessary. Write
`reconciliation.json` beside the requested output, including for alternate
output paths. All inputs needed to compute a refresh are supplied as CLI
arguments or source workbook sheets; do not hardcode particular event IDs,
groups, SKU names, date cutoffs or file locations.

Source sheets: Events, Lines, Products, Aliases, Contracts, OperatorNotes.
Copy these into the output without changing their nonempty cell values.
Equivalent cached booleans after an office save are acceptable.
Retain OperatorNotes merged ranges, freeze panes, review-cell fills and comment
texts; the notebook is human-owned, not generated. Do not recreate it from a
few remembered cell values.

Add these generated sheets (all tables start at A1):

* **Detail**, columns in this order:
  event_id, purchase_line, group, quarter, kind, eligible_cents.
  Exactly one row for each selected active event through cutoff. eligible_cents
  is a signed integer, not dollars. Ordering is free. No extra totals row.
* **Summary**, columns:
  group, quarter, net_cents, rate_bps, entitlement,
  previous_entitlement, adjustment.
  Exactly one row per required key; no totals row. net_cents is nonnegative.
  entitlement, previous_entitlement, adjustment are dollar amounts.
  net_cents, rate_bps, entitlement and adjustment MUST be live Excel formulas,
  not pasted values; net_cents depends on Detail and rate_bps follows Contracts.
  This means editing a Detail eligible_cents cell across a tier boundary and
  recalculating updates net, rate, entitlement and adjustment without Python.
  previous_entitlement is the frozen prior entitlement value.
  Additional columns to the right are allowed. No external workbook links.
* **Dashboard**: a real column/bar chart linked to every Summary adjustment,
  with group category labels in corresponding order. Include negative amounts;
  a screenshot, static picture or chart of purchases instead does not count.

Save an Excel-compatible .xlsx. Cached values are useful for users; the verifier
will independently recalculate a COPY with LibreOffice before judging values.
Your refresh need not invoke LibreOffice itself if the formulas are correct.
No prescribed sheet styling beyond retaining the human notebook.

`reconciliation.json` must contain at least:

```
{
  "as_of": "YYYY-MM-DD",
  "source_sha256": "<SHA256 of the input xlsx bytes>",
  "active_event_count": 123,
  "void_event_ids": ["selected VOID IDs through the cutoff"],
  "detail_total_cents": 12345,
  "adjustment_total": 12.34
}
```

Use a JSON number for adjustment_total. void_event_ids is a set represented as a
list; order does not matter. Include only selected VOID events with occurred_on
<= cutoff. Counts and totals cover Detail, including zero-valued events.
The report must describe this actual source and approved-close comparison.
