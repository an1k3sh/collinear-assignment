# Stockroom Savepoints: build a transactional fulfillment interpreter

A warehouse team has specified a small language for reserving and shipping
multi-line bundles. They need an interpreter before they can replace their
manual dispatch scripts. Transactions must prevent partial orders, leaked holds,
and audit events describing shipments that never committed.

Build the interpreter in `/app/stockroom` and implement
`/app/workflows/fulfill.stock`. The complete
contract is `/app/docs/language.md`; the business workflow is specified in
`/app/docs/fulfillment.md`. Start with those documents, the incident program and
input in `/app/incident`, and `python -m unittest discover -s smoke -v`.

## Required outcome

1. Implement the documented CLI and complete language contract:
   parsing and static validation, lexical procedure/block scope, atomic inventory
   operations, nested transactions, recovery, nonlocal control flow, event
   buffering, diagnostics, and all-or-nothing file publication on failure.
   The package is a starting skeleton, not an existing implementation to repair.
   Choose your own parser, intermediate representation, and execution model.
2. Implement the reusable `fulfill` procedure, not just the supplied orders.
   Leave the incident driver unchanged. The verifier also appends fresh drivers
   to your workflow and uses different inventories and quantities.
3. Run:

   ```sh
   python -m stockroom /app/incident/run.stock \
     --library /app/workflows/fulfill.stock \
     --inventory /app/incident/inventory.json \
     --out /app/deliverable/result.json
   ```

   Leave the resulting JSON and `/app/deliverable/HANDOFF.md`, explaining the
   design decisions, the checks you actually ran, and the incident outcome.

Use only Python's standard library. No external services, credentials, packages,
or network access are necessary. Do not change the documents, incident inputs,
or public smoke tests. Do not read or modify `/tests` or `/solution` if mounted
later by the evaluation harness. There is no required internal architecture.

Acceptance checks meaningful state and events, fresh valid and invalid programs,
recoverable versus fatal failures, and preservation of an existing output file
when any run fails. JSON object key order and diagnostic prose are not graded.
The two-hour allowance is not a speed target.
