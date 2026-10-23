# Stockroom interpreter: handoff

## What's in this folder

| Path | Contents |
|---|---|
| `/app/stockroom/` | Interpreter package (standard library only), run with `python -m stockroom` |
| `/app/workflows/fulfill.stock` | Reusable `fulfill` procedure (a library with no `main` and no helper procedures) |
| `/app/deliverable/result.json` | Final incident result, published by the last resumed invocation (exit 0) |
| `/app/deliverable/checkpoint.json` | Last checkpoint (pause 7, `delta:reserved`), unchanged by completion |
| `/app/checks/` | My own tests: a harness, semantic and CLI tests, and a differential resume fuzzer |

`/usr/local/lib/python3.12/site-packages/stockroom-app.pth` contains `/app`, so
`python -m stockroom` also works from any working directory.

## Design decisions

* **Pipeline.** Each file goes through a hand-written lexer and a recursive-descent parser to produce an AST. The library is parsed first, then the program. A single static pass then checks and compiles each procedure into a flat bytecode list. Static checks cover scopes, types, calls and arguments, emit keys, recovery-binding rules, break/continue placement and recursion (a DFS over every call site, including unreachable ones). The whole unit is validated before anything executes. Expressions compile to closures; they never contain calls to user procedures, so they can't pause.
* **Explicit VM state (no host recursion across statements).** Each frame holds a procedure name, a pc, and a block stack. Blocks are `["s", scope]`, `["l", loop_pc]` or `["t", tx_pc, journal_mark, event_mark]`.
  * `break`, `continue` and `return` pop blocks and commit every transaction they leave (`committed += 1`). They are not exceptions and are never caught by `recover`.
  * DOMAIN failures unwind blocks and frames. Every transaction they pass counts toward `rolled_back`. The first transaction with a handler restores state and enters its recovery block in a new scope that binds the error.
* **Transactions use an undo journal** rather than copies. While any transaction is active, the journal records the old values of warehouse/SKU entries, hold records and variable assignments (by frame and block index, so caller frames are covered). Rollback replays the journal back to the transaction's mark and truncates the event buffer to its saved length. A successful inner transaction leaves its entries in place, so an outer rollback still undoes it. Event IDs are only assigned at publication, so aborted emits consume no IDs.
* **Checkpoints serialize the VM directly.** The `state` object holds the frames, scopes, transaction marks, journal, warehouses, holds, buffered events and counters. Recovery errors are stored as `{code, file role, line, column, stack}`. On resume, the envelope and checksum are validated first, then the SHA-256 identity of the program, inventory and library bytes, and only then is the program compiled. The state is then checked strictly against the compiled program:
  * The top frame must sit right after a PAUSE and each caller frame right after a CALL to the next frame's procedure.
  * Each block stack must match the static block shape recorded at that site, and scope names and value types must match the declarations.
  * Journal and event marks must be monotonic, holds must not exceed on-hand stock, and counters must be valid.

  Anything else, including `state:{}`, is rejected as CHECKPOINT (8). Steps, `committed`, `rolled_back` and `pause_count` are cumulative across processes, and the 20,000-step budget is global. Diagnostics store a file *role* rather than a path, so relocated files report their current paths.
* **Publication.** Each output is written to a temporary sibling, fsynced, then `os.replace`d. Only the result is published at completion, and only the checkpoint at a pause. Alias rules and missing parent directories are rejected as IO before anything executes. Every error path leaves existing files untouched.
* **Workflow.** `fulfill` decides shortage with an exact availability test before reserving, and that test handles SKU A and SKU B being the same. Each warehouse attempt is a single transaction: reserve `.a`, reserve `.b`, `pause order + ":reserved"`, ship both, then emit one `fulfilled` event. If neither warehouse fits, it emits `deferred` with reason `SHORTAGE`.
  * Nothing is caught, so other domain errors (WAREHOUSE, QUANTITY, NAME, DUPLICATE_HOLD) propagate with their original code, location and stack.
  * Quantities ≤ 0 or empty SKUs skip the test so the operation itself reports the error.
  * There are no helper procedures, so drivers appended to the file can't collide with internal names.
* **Interpretation choices.** These are the points I settled where the spec is not explicit:
  * A reserved keyword used as an identifier is SYNTAX.
  * `onhand`/`available` return 0 for a missing SKU (the NAME rule applies to atomic operations).
  * `remaining` of an unknown or empty ID is HOLD.
  * Bad CLI usage is IO.
  * `main` must be defined in the program file. A library-only `main` is STATIC.

## Checks actually run

* `python -m unittest discover -s smoke -v`: both public smoke tests pass.
* `python -m unittest discover -s checks` (29 tests). Every successful program in the semantic tests is also run through a pause/resume chain, with files relocated to a new directory and the originals deleted before each new process, and the result must match the uninterrupted run. The tests cover:
  * arithmetic and truncating division
  * step/commit/rollback counters
  * break/return commits
  * nested rollback and errors inside recovery
  * restoring caller-frame bindings
  * shadowing, including of recovery bindings
  * named/default arguments
  * every operation's error code
  * short-circuit evaluation
  * the exact 20,000/20,001 step limit, both uninterrupted and across a pause
  * RUNTIME/DOMAIN diagnostics with line, column and stack
  * 49 STATIC cases, 14 SYNTAX cases and 12 INPUT cases
  * 20+ checkpoint corruption and forgery cases, including `state:{}`
  * identity changes (a one-space source change, whitespace in the input, library presence)
  * path aliases through `..`
  * missing parent directories
  * file preservation on failure
  * repeated resume of the same checkpoint
  * fulfill scenarios: preferred, fallback, same SKU, deferred, inside a caller transaction that later rolls back, same-named caller locals, and non-shortage errors propagating
* `python checks/fuzz_resume.py 3000 1` and `3000 7`: 6,000 random typed programs (procedures, loops, nested transactions/recovery, pauses everywhere, failing operations), each run uninterrupted and then suspended → JSON → reloaded at every pause. All 6,000 matched exactly, including DOMAIN/RUNTIME diagnostics.
* An independent read-only spec review found one gap: a library-only `main` was accepted. I fixed it, added a regression test and reran everything above.
* Performance check: a 1 MiB inventory with about 9k steps and 1,500 rollbacks ran in about 0.15 s. A 60,000-term expression and 3,000 nested parentheses evaluate without hitting recursion limits.

## Incident execution

Commands, in separate processes: the documented command once, then the same
command with `--resume /app/deliverable/checkpoint.json` until exit 0.

| Invocation | Exit | Pause label (count) |
|---|---|---|
| 1 | 10 | `practice:reserved` (1) |
| 2 | 10 | `rehearsal:before-abort` (2) |
| 3 | 10 | `ASSERT` (3) |
| 4 | 10 | `alpha:reserved` (4) |
| 5 | 10 | `dispatch:after-alpha` (5) |
| 6 | 10 | `beta:reserved` (6) |
| 7 | 10 | `delta:reserved` (7) |
| 8 | 0 | result published |

**7 pauses.** The final `result.json` is byte-identical to an uninterrupted run, and an extra resume of the last checkpoint into another output produced identical bytes.

Outcome:
* The rehearsal fulfilled `practice` from east, paused twice, then hit `assert false`. The rollback undid the `practice` holds, shipments, event and the `attempts` assignment. The recovery then emitted `rehearsal_reverted {attempts: 0, reason: "ASSERT"}`, and the program paused on `ASSERT`.
* `alpha` (gear 6 + seal 6): east had only 5 seals, so the order shipped from **west** (12 units).
* `beta` (gear 5 + seal 3): west had only 3 free gears, so the order shipped from **east** (8 units).
* `gamma` (gear 8 + seal 8): east had 4 free gears because of the `safety` hold, and west had 3, so the order was **deferred** (SHORTAGE) with no holds and no change to stock.
* `safety` was released, then `delta` (gear 4 + seal 2) shipped from **east** (6 units).
* Closing: `east_gear: 3`, `west_gear: 3`.
* Final stock: east gear 3 / seal 0, west gear 3 / seal 6, overflow 0 / 0.
* Holds: `safety`, plus `.a`/`.b` for alpha, beta and delta, all closed with 0 remaining.
* 6 events. Stats: `{"steps": 86, "committed": 4, "rolled_back": 1}`.
