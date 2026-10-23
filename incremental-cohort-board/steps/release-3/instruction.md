# Release 3: publish rate-band analysis safely

Add the `rated` report from `/app/docs/contract.md` while preserving `inner` and
`outer`. Rate imports and classification corrections can occur in the same
transaction. Rate rows are not a unique lookup by segment.

Continue the existing database using `python demo.py --through 3`. Deliver all
three correct materialized reports, durable auxiliary state, source/receipt
preservation, regression checks and an updated `/app/REPAIR_REPORT.md`.

The verifier checks all active releases, generated correction sequences,
rollback/retry/reopen, and the stated 300,000-instruction locality bound.
Successful smoke checks alone are not release approval. Validate the projection
against the reference SQL after meaningful state transitions.
