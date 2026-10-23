# Durable execution extension 2.0

This extends language 1.0; all its other rules remain in force.

## Pause statement

`pause expression;` is a statement. Its expression must statically be `string`.
It is legal anywhere a statement is legal, including nested procedures, loops,
transactions and recovery blocks. `pause` is a reserved syntax keyword.
Any string, including empty or repeated labels, is valid. Labels identify
observations, NOT unique continuation addresses.

With neither `--checkpoint` nor `--resume`, pause evaluates its expression and
counts as one entered statement but otherwise does nothing. This is the
uninterrupted reference behavior.

With durability enabled, each encountered pause evaluates its expression,
increments steps and the cumulative pause count exactly once, saves execution
immediately AFTER that statement, and exits **10**. This is a successful
suspension, not an error, domain failure, commit, or rollback. No result file
is created or changed. No diagnostic is printed to stderr.

## CLI

The original CLI additionally accepts:

* `--checkpoint PATH`: enable suspension and publish each new checkpoint here.
* `--resume PATH`: start from a saved checkpoint, not from main's entry.
  Durability is enabled. If `--checkpoint` is omitted, replace the resume path
  on the NEXT pause; if supplied, publish there instead, leaving resume input
  unchanged. Using the same path for both is allowed.

PROGRAM, INPUT and optional LIBRARY are still required on resume as on initial
execution. Their UTF-8 bytes must exactly match the checkpoint's fingerprints.
Paths may differ; file bytes, role and library presence are authoritative.
Whitespace-only source/input changes still invalidate identity. Read errors
are IO (7); a readable but nonmatching input/source is CHECKPOINT (8), even if
the changed file is not valid source/JSON. Validate identity before compiling.

On normal completion, publish the original result schema and exit 0. Do NOT
change or delete the checkpoint file. Thus the last checkpoint remains a
reusable, immutable snapshot unless explicitly replaced by a later pause.
Resuming a snapshot repeatedly must produce the same suffix and final result.
This is intentional deterministic replay, not consumption of a one-use token.
No external database, network, wall-clock or irreversible effect exists here.
Exactly-once means committed state/events contain no duplicated prefix effects,
not that repeating the CLI invocation is prohibited.

Missing parent directories or unwritable publication paths are IO (7). Validate
path aliases before executing: output cannot resolve to PROGRAM, INPUT,
LIBRARY, checkpoint input, or checkpoint output; checkpoint output cannot resolve
to PROGRAM, INPUT or LIBRARY. Reject aliases as IO without changing files.
Tests use ordinary paths, copies and `..` aliases, not concurrent path races.

## Portable checkpoint envelope

The saved file must be one UTF-8 JSON object with exactly these fields:

```
{
  "format": "stockroom-continuation",
  "version": 1,
  "identity": {
    "program": "<64 lowercase hex SHA-256 of PROGRAM bytes>",
    "inventory": "<64 lowercase hex SHA-256 of INPUT bytes>",
    "library": null
  },
  "label": "awaiting-dispatch",
  "pause_count": 1,
  "state": {"<implementation-defined execution state>": "..."},
  "checksum": "<64 lowercase hex SHA-256>"
}
```

With a library, `identity.library` is its SHA-256 instead of null.
`version` and `pause_count` are integers, not booleans; version must equal 1,
pause_count must be positive. Label is a string and state is a JSON object.
State's INTERNAL representation is your choice. No required key order.

Checksum covers the ENTIRE envelope with only `checksum` removed, encoded as:

```
json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
           allow_nan=False).encode("utf-8")
```

Hash those bytes with SHA-256 and store lowercase hexadecimal. Duplicate JSON
keys, NaN/Infinity, invalid JSON, invalid field types, unsupported format/version,
incorrect checksum, missing required fields and incompatible execution state
are CHECKPOINT (8). Print one JSON diagnostic with `error:"CHECKPOINT"` and a
nonempty message. No source location or stack is required for this category.
The file is at most 16 MiB. Reject `state:{}` as incompatible state even when
its checksum is recomputed. Acceptance does not require detecting every forged,
rechecksummed implementation-specific state. Checksum detects corruption,
not malicious authorship; never use pickle, eval, exec or unsafe deserialization.

## What must survive

The next executable instruction; procedure call/return targets; current loop
positions; active lexical scopes and shadowed bindings; warehouse and hold
records (including closed holds); tentative event ordering; active transaction
snapshots and recovery targets; bound recovery errors; original failure
locations/stacks where applicable; and all execution counters.

A pause is NOT a transaction boundary. An outer rollback after restart undoes
inner transactions and recoveries that occurred before suspension. Return,
break and continue after restart commit exactly the transactions they exit.
Rollback counters and completed-inner-transaction counters remain cumulative
across both pause and later outer rollback. Step budget is 20,000 across the
whole execution, NOT a fresh allowance per process. A resumed pause is already
executed and must not be entered or counted again.

Recovery error bindings must remain valid across pause, with `code(e)` and
lexical shadowing retaining their meanings. Labels can repeat in a loop or in
different procedures; each dynamic pause advances the execution exactly once.

Checkpoint JSON is the only durable state. Tests may retain ONLY the checkpoint,
byte-identical source/library/input, and your installed implementation, remove
the originals and working directory, and start another interpreter process.
No sidecars, absolute-path dependencies, `/tmp` caches, daemons or kept workers.
Implementation strategy is free: explicit VM state, continuations, or safe
deterministic reconstruction are acceptable if all observable semantics agree.

## Publication and failure boundaries

At a pause, atomically replace only the checkpoint output using a temporary
sibling; leave result output unchanged. At completion, atomically replace only
the result output; leave checkpoint bytes unchanged. On any failure leave BOTH
preexisting outputs unchanged, or absent if they were absent. Do not prewrite
an initial checkpoint before reaching a pause. Result/checkpoint publication
never requires a two-file commit because only one is published per invocation.
Also preserve a distinct resume input. Sources and inventory are read-only.

This task tests clean suspension and process restart, not killing the process
mid-write or exactly-once integration with an external service.
