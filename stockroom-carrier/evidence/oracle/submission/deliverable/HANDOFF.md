# Carrier recovery

Built the typed interpreter and explicit durable continuation machine. Local
transactions snapshot warehouse, hold, delivery, event and binding state; they
never snapshot or rewind the independently committed carrier database.
Receipt lookup, not timeout outcome or current routing preference, determines
existing acceptance. Stable order keys bind the original ordered payload.
Closed holds and local delivery records prevent repeated application.

The source evidence for orphan describes an interrupted west request and no
published local record; its authoritative receipt confirms west acceptance.
The rehearsal rollback removes drill's local effects, not its carrier receipt.
Alpha's timeout follows acceptance; beta's precedes it. Both converge safely.
Blocked is rejected; gamma is deferred without a carrier request.

Ran the legacy incident and carrier incident through all pauses in fresh CLI
processes. Carrier incident final stock: east gear/seal 17/12; west 17/28.
Local and external accepted order sets are drill, alpha, beta, orphan.
Repeated alpha is a local no-op. The live database and both last checkpoints
remain for independent replay.
