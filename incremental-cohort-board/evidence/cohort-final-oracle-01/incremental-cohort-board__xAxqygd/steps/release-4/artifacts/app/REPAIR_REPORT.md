# Incremental projection handover

Fixed invalidation of old/new account neighborhoods, tag multiplicity and
dimension-only corrections. Each account contributes at most one auxiliary
row per report/group. Count, non-NULL count, sum and distinct-account membership
are updated by contribution differences; indexed extrema permit deletion of
an old minimum/maximum without rescanning a large group.

Group NULLs use lossless JSON tuple keys; SQL joins still use ordinary equality.
Both before and final images drive reverse dependency discovery. All persistent
state participates in the host transaction and survives process restart.
Explicit upgrade rebuilds all active reports but ordinary batches do not.

The household release stores account/component identities and per-bucket
household support. A link edit re-traverses the union of old components and
their final graph neighborhoods, so deleted bridges can split a class.
Distinct counts change only when per-group support crosses zero. Dormant
vertices participate in connectivity without contributing joined amount rows.

Ran public regression checks and the current release's incident replay with
the commands in solution/oracle.sh. Broader checks are supplied independently
by the verifier. No outside services or numeric rate computation is used.
