# Stockroom language 1.0

This is the authoritative contract, not a list of hints about the current bugs.
All numbers are arbitrary-precision signed integers; booleans are not integers.
All programs and inputs used for acceptance fit the published limits.

## CLI and files

`python -m stockroom PROGRAM --inventory INPUT --out OUTPUT [--library LIBRARY]`

An optional library's procedure definitions precede the program's definitions.
Forward calls are allowed across both files. Every program has `proc main()`.
Library and program together are one compilation unit, validated in full before
execution, including unreachable branches and uncalled procedures.

The input JSON has exactly `warehouses`, an object mapping warehouse names to
objects mapping SKU names to nonnegative integer on-hand quantities.
Names are nonempty strings. Empty warehouse maps are allowed. Missing SKU in a
known warehouse means zero. Unknown warehouse is a recoverable `WAREHOUSE` error.
Input with extra top-level fields, duplicate JSON keys, booleans as quantities,
negative quantities, invalid JSON or wrong shapes is `INPUT`.

Success publishes one UTF-8 JSON object, replacing OUTPUT:

```
{
  "warehouses": {"east": {"widget": 5}},
  "holds": {"order.a": {"warehouse":"east","sku":"widget","remaining":2}},
  "events": [{"id":1,"name":"picked","data":{"order":"order"}}],
  "stats": {"steps":7,"committed":1,"rolled_back":0}
}
```

Preserve explicitly present zero SKU entries; do not create missing SKU entries
on reads or failed operations. Successful mutating operations create affected
SKU entries, including a zero at the source. Holds remain present after their
remaining quantity reaches zero; IDs cannot be reused, even for closed holds.
On-hand includes held stock. Each warehouse/SKU satisfies
`0 <= sum(remaining holds) <= onhand`; available is the difference.

Output parent directories must already exist. Write a temporary sibling, then
replace OUTPUT only after compilation, execution and serialization succeed.
No failure may change an existing OUTPUT (or create OUTPUT if absent).
Do not modify INPUT, PROGRAM, or LIBRARY. No other output files are required.
No stdout contract. One JSON diagnostic goes to stderr on error:

| exit | error | category |
|---|---|---|
| 2 | SYNTAX | malformed source, including illegal tokens |
| 3 | STATIC | invalid names/types/calls/control flow or recursion |
| 4 | DOMAIN | an unhandled recoverable inventory/assert failure |
| 5 | RUNTIME | division by zero, step limit |
| 6 | INPUT | malformed inventory |
| 7 | IO | source/input read or result publication failure |

Every diagnostic has `error` and nonempty `message`. Source-related errors also
have `file`, `line`, `column` (1-based token-start positions). DOMAIN and RUNTIME
also have `stack`: ordered procedure names from main to the failing procedure.
Unhandled DOMAIN includes `code`. A failure caught and rethrown without a
handler keeps its original location/stack. Exact message text is not graded.

## Grammar

Whitespace and `//` comments outside strings are ignored. Identifiers match
`[A-Za-z_][A-Za-z0-9_]*`; keywords are reserved. Strings use JSON double-quoted
syntax. Integers are decimal; negative literals use unary minus.
Only the constructs below are supported. Semicolons shown here are mandatory.
No Python evaluation, filesystem access, imports, or host-language escape.

```
program   := procedure*
procedure := "proc" NAME "(" [parameter ("," parameter)*] ")" block
parameter := NAME ":" TYPE ["=" literal]
TYPE      := "int" | "bool" | "string"
literal   := INTEGER | "-" INTEGER | STRING | "true" | "false"
block     := "{" statement* "}"
statement := "let" NAME ":" TYPE "=" expression ";"
           | "set" NAME "=" expression ";"
           | "if" "(" expression ")" block ["else" block]
           | "while" "(" expression ")" block
           | "transaction" block ["recover" "(" NAME ")" block]
           | "break" ";" | "continue" ";" | "return" ";"
           | "assert" expression ";"
           | "emit" expression "{" [NAME ":" expression
                                     (";" NAME ":" expression)* [";"]] "}" ";"
           | "receive" "(" expression "," expression "," expression ")" ";"
           | "move" "(" expression "," expression "," expression "," expression ")" ";"
           | "reserve" "(" expression "," expression "," expression "," expression ")" ";"
           | "release" "(" expression "," expression ")" ";"
           | "ship" "(" expression "," expression ")" ";"
           | NAME "(" [argument ("," argument)*] ")" ";"
argument  := [NAME "="] expression
```

No duplicate procedures, parameters, block-local declarations or emit keys.
Required parameters precede defaulted parameters. Default literals must have
the exact declared type. Entry main has no parameters. A procedure's outer
body block shares its parameter scope; child blocks may shadow outer bindings.
A variable's initializer cannot see the variable being declared; it can see an
outer variable with that name. No global variables. Each procedure sees only
its own parameters/locals, never its caller's local variables.

Arguments evaluate left-to-right in caller scope; positional arguments precede
named ones; reject missing, extra, unknown or multiply-bound arguments.
Procedures return no value. Builtins cannot be used as statements; procedures
cannot be used as expressions. Direct and indirect recursion is statically
forbidden even in unreachable code. `return;` exits the current procedure only.
`break`/`continue` require a loop in the same procedure, not in a caller.

## Expressions and static types

From low to high precedence: `||`, `&&`, `== !=`, `< <= > >=`, `+ -`, `* / %`,
unary `! -`, primary (literal, variable, builtin call, parenthesized expression).
Binary operators associate left. Comparisons are ordinary binary operations,
not Python-style chains. `&&` and `||` short-circuit at runtime, but both operands
are statically checked. `!`, conditions, and assert require bool.
`+` accepts int/int or string/string. Other arithmetic and unary `-` require int.
`/` truncates toward zero; `a % b = a - (a / b)*b`. Division/modulo by zero is
fatal RUNTIME. Equality needs identical types. Ordering permits int/int or
string/string only. No implicit conversions.

Builtins (positional arguments only):

* `onhand(warehouse:string, sku:string) -> int`
* `available(warehouse:string, sku:string) -> int`
* `remaining(id:string) -> int`: unknown hold gives recoverable `HOLD`
* `len(value:string) -> int`
* `code(error) -> string`: accepts a recovery error binding only

Recovery bindings have an internal error type: they can be shadowed in a child
block but cannot be assigned, redeclared in their own block, passed to user
procedures, emitted, compared, or used except as the argument of `code`.
Emit name must be string; payload values may be int/bool/string only.
Builtin names are reserved against procedure definitions (variable names may
use them). Reserved syntax keywords cannot be identifiers.

## Atomic operations

Operands evaluate left-to-right, then validate without mutation on any failure.
All quantities must be positive integers (type checked statically, positive at
runtime), else recoverable `QUANTITY`. All IDs, warehouse and SKU operands are
strings; empty hold IDs or SKU operands give recoverable `NAME`.
For multi-invalid domain inputs validation precedence is unspecified.

* `receive(warehouse, sku, qty)`: increase on-hand.
* `move(source, destination, sku, qty)`: move FREE stock only. Both warehouses
  must exist; same warehouse gives `SAME_WAREHOUSE`. Insufficient available
  stock gives `SHORTAGE`. Either both on-hand values change, or neither does.
* `reserve(id, warehouse, sku, qty)`: create a hold from FREE stock. Duplicate
  ID (including closed hold) gives `DUPLICATE_HOLD`; shortage gives `SHORTAGE`.
* `release(id, qty)`: reduce hold by qty without changing on-hand; qty larger
  than remaining gives `SHORTAGE`; unknown ID gives `HOLD`.
* `ship(id, qty)`: reduce both hold remaining and its warehouse's on-hand;
  qty larger than remaining gives `SHORTAGE`; unknown ID gives `HOLD`.
* `assert false`: recoverable `ASSERT`.

## Transactions, scopes and control flow

Each brace block is a fresh lexical scope except procedure outer bodies.
`set` assigns the nearest existing binding. Assignment is never declaration.

A transaction snapshots ALL warehouse entries, hold records, the ordered event
buffer and values of every currently active lexical binding, including caller
frames. On a recoverable DOMAIN failure restore this complete snapshot first.
Then, if present, run its recovery block in a fresh scope binding its error.
Recovery is outside that transaction but inside enclosing transactions.
An error inside recovery propagates to the enclosing handler, not the same one.
With no recovery, propagate the original error after rollback.

A successful inner transaction remains tentative within an outer transaction.
An outer rollback undoes it, including any events from successful inner blocks
or inner recoveries and all variable assignments made after the outer entry.
Fatal RUNTIME errors are never caught by `recover`; no output is published.

`return`, `break`, `continue` are successful control transfers, not failures:
commit every transaction exited on the way to their destination. A procedure's
return does not commit a transaction in its caller that has not been exited.
Never use control-transfer signals as recoverable errors.

Emits append events in execution order. Assign IDs 1..N only to final surviving
events: aborted emits consume no IDs. Preserve payload scalar types.

Stats are diagnostic execution counters, NOT transactional state:
`committed` counts transaction bodies exited successfully, including via
control transfer, even if later rolled back by an outer transaction.
`rolled_back` counts each transaction body unwound by DOMAIN, handled or not.
Recovery blocks are not transactions. `steps` counts each entered statement AST
node once, including let, call, transaction, if/while, emit and control transfers.
A while node counts once per encounter, not per iteration; its body's statements
count on every iteration. Expressions, conditions, blocks, and implicit main
entry do not count. Fail with fatal RUNTIME before statement 20,001.
Limits: at most 20,000 entered statements, 32 nested procedure calls, 32 nested
transactions, 64 nested blocks, 1 MiB source and 1 MiB input. Programs exceeding
syntactic nesting or call/transaction depth limits are outside acceptance scope;
the step-limit failure is explicitly tested. No wall-clock-dependent semantics.
