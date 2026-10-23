# April reconciliation

Batch IDs are merchant-scoped; deposits are matched by explicit references,
not amounts. Latest revisions are selected as known at cutoff before excluding
cancelled/future-effective items. Late-recorded April adjustments are not
retroactively included. Holds/releases affect reserve assets, not fee expenses.

North B-18 has a 225-cent shortfall. North B-19 is pending settlement, not an
unexplained loss. Invoice aging uses acceptance plus terms. Draft credits do not
reduce receivables, and exact text IDs preserve the two North invoices.

Rerun command: `python submission/reconcile.py --input data --output submission/close`.
The output is deterministic under reordered input and recomputed from source.
