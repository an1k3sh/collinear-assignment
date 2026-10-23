# Stockroom Carrier: implement and reconcile a durable dispatch language

An operations team needs an interpreter for its warehouse language and a reusable
dispatch workflow. An interrupted carrier integration left local dispatch
records and carrier observations disagreeing. Determine the incident outcome
from the supplied evidence, finish the implementation and recover the batch.

## Start here

* `/app/docs/language.md` defines the base imperative language.
* `/app/docs/durability.md` defines pause/resume.
* `/app/docs/carrier.md` defines the external-effect extension and service API.
  Where it explicitly extends the earlier contracts, this document takes
  precedence.
* `/app/docs/fulfillment.md` defines the legacy fulfillment library.
* `/app/docs/dispatch.md` defines the new reusable dispatch library.
* `/app/carrier-incident/` contains inventory, a fixed driver, source evidence,
  and the immutable carrier seed. `/app/carrier/state.sqlite` is the live local
  mock carrier, initialized from that seed.
* `python -m unittest discover -s smoke -v` runs public, incomplete examples.

The interpreter package `/app/stockroom` is a skeleton, not a seeded bug hunt.
Implement the documented language, durable continuation and carrier semantics.
Implement both `/app/workflows/fulfill.stock` and
`/app/workflows/dispatch.stock`. Only Python's standard library is permitted.
You may inspect the supplied carrier implementation and its SQLite read
interface. Do not modify `/app/carrier_service.py`, the documents, incident
inputs, carrier seed, or smoke tests. Carrier writes must go through the supplied
service API; do not repair or overwrite its database directly.

## Required outcomes

1. A reusable interpreter, not a one-off incident calculation. It must support
   the full base language and pause/resume, and distinguish the state boundaries
   described in the carrier protocol.
2. A reusable dispatch procedure satisfying `/app/docs/dispatch.md` for fresh
   orders, histories, stock quantities, outages and receipt IDs.
3. Run the legacy durable incident through all pauses, preserving its original
   deliverables:

   ```sh
   python -m stockroom /app/incident/run.stock \
     --library /app/workflows/fulfill.stock \
     --inventory /app/incident/inventory.json \
     --out /app/deliverable/result.json \
     --checkpoint /app/deliverable/checkpoint.json
   ```

4. Recover the carrier incident through all pauses:

   ```sh
   python -m stockroom /app/carrier-incident/run.stock \
     --library /app/workflows/dispatch.stock \
     --inventory /app/carrier-incident/inventory.json \
     --carrier /app/carrier/state.sqlite \
     --out /app/deliverable/carrier-result.json \
     --checkpoint /app/deliverable/carrier-checkpoint.json
   ```

   Exit 10 is a successful pause. Repeat each command with `--resume` pointing
   to its checkpoint until exit 0. Create `/app/deliverable` first. Leave both
   result/checkpoint pairs, the live carrier database and a nonempty
   `/app/deliverable/HANDOFF.md`. Explain your evidence-backed diagnosis, state
   boundaries and checks actually run. Prose wording is not string-graded.

The verifier checks arbitrary programs and generated recovery batches, not just
these incidents. It restarts fresh processes, relocates checkpoint/source/input
files, and tests both replay against an advanced carrier and rejection of a
different carrier identity. Source and input bytes must remain unchanged.

No real network service, credentials, external packages or randomness are
needed. The supplied mock carrier is local and deterministic. Do not access
verifier/oracle files if mounted later. The two-hour allowance is not a speed
target. Earlier model passes do not establish that this revision fails a model.
