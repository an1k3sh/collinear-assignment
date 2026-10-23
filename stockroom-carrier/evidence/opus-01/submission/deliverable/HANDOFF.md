# Stockroom carrier incident — handoff

## Outcome

Both batches were run through every pause to exit 0 with the exact commands from
the task (each resumed with `--resume` on its own checkpoint):

| batch | pauses | result | checkpoint left |
|---|---|---|---|
| legacy `incident/run.stock` + `fulfill.stock` | 7 | `result.json` | `checkpoint.json` (label `delta:reserved`) |
| `carrier-incident/run.stock` + `dispatch.stock` | 15 | `carrier-result.json` | `carrier-checkpoint.json` (label `blocked:reserved`) |

Carrier incident final local state: east gear 17 / seal 12, west gear 17 / seal 28.
Deliveries: `drill` (east), `alpha` (east), `beta` (east), `orphan` (west,
`receipt-imported-z9`). `blocked` was rejected, `gamma` deferred (SHORTAGE), the
repeated `alpha` call was a local no-op.

Live carrier `/app/carrier/state.sqlite` after recovery (written only through
`Carrier.submit`), with one acceptance per key:

* accepted: `orphan` (seeded import, untouched), `drill`, `alpha`, `beta`
* attempts: drill accepted; alpha timeout_after_accept; beta timeout_before_accept;
  beta accepted; blocked rejected. That is five submissions in total and at most
  two for any key.

## Evidence-backed diagnosis

* **orphan**: the seed/database already holds an acceptance
  (`receipt-imported-z9`, west, gear 3 / seal 2), and no local delivery exists
  ("No published local completion record"). The connector evidence confirms
  the earlier request used west and the stable key `orphan`. Current preferences
  (east first) were changed after the interruption, according to the operator,
  and are not shipment history. So orphan was reconciled **at west with the
  existing receipt**: no new submission, no redirect to east.
* **alpha** (`accept_then_timeout_once`, "response loss"): the first submit was
  accepted but reported `CARRIER_TIMEOUT`. Local effects were rolled back, and a
  receipt lookup showed the acceptance, which was posted locally. There was no
  second shipment and no new key.
* **beta** (`timeout_before_once`, "transport interruption"): the timeout left
  no acceptance (lookup was empty), so the workflow retried with the same key
  and payload, which was accepted.
* **blocked** (`reject`): one `rejected` event, no holds, debit or delivery.
* **drill** (operator rehearsal): accepted inside a rehearsal transaction that
  was then aborted. The local rollback removed holds, debit, event and
  delivery, but **not** the carrier acceptance. The next `dispatch_order("drill",
  ..., "west", "east")` reconciled that acceptance at its recorded warehouse
  (east) despite the new preference, without submitting again.

## State boundaries

1. **Local transactional state**: warehouses, holds, events, variables, and
   `deliveries`. A journal records changes so a transaction can roll them back;
   these values are persisted only through the checkpoint.
2. **Carrier (external, irreversible)**: acceptances and the attempt log. Local
   rollback, failures, and loading older checkpoints never rewind it.
   Checkpoints bind only its `service_id` (a different ID gives CHECKPOINT 8;
   a missing database gives IO 7), never its path or contents.
3. **Checkpoint file**: published only at a pause, by atomic temp file and
   rename. **Result file**: published only at completion. On error neither is
   touched.

Resume uses deterministic replay. The checkpoint state stores the pause count,
the step count, a SHA-256 digest of local state at the pause, and a log of
every carrier *observation* the run made (lookup results and submit
receipts/failures). It holds no copy of the database. Resuming re-executes
from `main` against byte-identical sources and input. Carrier builtins read
from the log rather than contacting the carrier. At the target pause the label,
steps, digest and log position are checked (any mismatch is CHECKPOINT), and
execution then continues live. As a result the suffix sees exactly the values
it saw before suspension, while the live suffix sees the current, possibly
advanced, carrier. The workflow looks up the receipt after every `:reserved`
pause and before any submit, so replaying an older checkpoint after the
carrier has advanced reuses existing receipts and never ships twice.

## Implementation

* `stockroom/lang.py`: lexer, parser and full static checker (types, scopes,
  recovery bindings, argument binding/defaults, recursion, `main` in program).
* `stockroom/runtime.py`: evaluator, journaled transactions, counters, inventory
  ops, carrier builtins, `record_delivery`, pause/replay.
* `stockroom/cli.py`: CLI, path-alias checks, identity/envelope validation,
  strict JSON input, atomic publication, and the adapter to the supplied
  `/app/carrier_service.py`.
* A `.pth` file in site-packages adds `/app` to `sys.path`, so `python -m
  stockroom` works from any working directory.
* `workflows/fulfill.stock`: preferred then fallback, deferring on SHORTAGE.
  Each attempt is atomic, with `order:reserved` after both holds; any
  non-SHORTAGE error fails explicitly through `assert`.
* `workflows/dispatch.stock`: no-op if already delivered. An existing
  acceptance forces its warehouse after a payload assert, and is never
  deferred or redirected. Otherwise preferred, then fallback (same-SKU lines
  summed), then deferred. The attempt runs in a transaction: reserve,
  `:reserved`, lookup or submit, ship, `record_delivery`, `fulfilled`,
  `:posted`. A TIMEOUT rolls back and retries (at most two submissions);
  REJECTED emits `rejected`; any other error fails explicitly. An acceptance
  appearing at another warehouse while paused causes a replan to that warehouse.

## Checks actually run

* `python -m unittest discover -s smoke -v`: all 3 pass.
* Both incidents dry-run first in `/tmp`, on a carrier freshly initialized from
  the seed. The durable results equal uninterrupted runs, and they match the
  live results.
* Ad-hoc suites in `/tmp`:
  * Control-transfer commits, nested and outer rollback of caller-frame
    variables, and step and step-limit (20,000) counting.
  * Truncating division/modulo, plus about 25 STATIC and 5 SYNTAX cases.
  * Domain codes and diagnostics (file, line, column, stack), and INPUT
    rejection.
  * Checkpoint tampering (`state:{}` with a recomputed checksum, bad checksum,
    duplicate keys, three-field identity, boolean version), all giving 8.
  * Relocated sources/carrier, changed bytes (8), wrong service ID (8), missing
    carrier (IO 7), and alias rejection.
  * Output untouched at pauses and checkpoints untouched at completion.
  * Repeated resumes of old checkpoints against an advanced carrier: same
    stock, holds, events and deliveries, and no extra acceptances. Only the
    diagnostic stats differ, because fewer timeouts were observed.
  * Dispatch scenarios: same-SKU lines, payload conflicts, accepted warehouse
    short of stock, timeouts inside an enclosing transaction, outer rollback
    then reapplication, replan when an acceptance appears during a pause, and
    isolation of caller locals.
* An independent review against the documents found three issues; all were
  fixed and every suite was rerun.
* The final carrier checkpoint was resumed against a *copy* of the advanced live
  database. The result was byte-identical and the checkpoint unchanged.
  The live database itself was never written outside the documented runs.
