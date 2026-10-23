# Dispatch incident 2026-04-19

09:04: The dispatcher migrated the global event sequence into the production
range. IDs/revisions did not reset. Desktop and handheld users then reported
different views of adjacent deliveries.

09:11: Van 7 recorded a visit while offline and queued a later assignment edit.
The first upload committed, but the access point lost its response. The tablet
restarted. Its retry conflicted instead of retrieving the original receipt.
A delayed receipt later made the unsent assignment disappear.

09:18: Another van generated the same local mutation ID; this is legal across
devices. It received a receipt containing the first van's device ID.

09:27: While dispatch was paging through a snapshot, the supervisor deleted a
valve work order and added an urgent work order alphabetically before the next
page. A snapshot is meant to describe one frozen cut, but its pages disagreed.

09:36: Reconnecting tablets advanced their cursor after a pushed notification.
Intervening work orders never appeared. Restarting a bootstrap halfway through
also briefly removed everything not on the latest page.

09:42: Fault injection after the projection write left an uncommitted work
order visible, despite the failed request. The archived database contains four
projection discrepancies. Events and successful receipts were independently
recovered from the durable journal and are authoritative.

The traces below are reduced reproductions, not exhaustive test cases.
Production had multiple tenants, deletes/restores, and concurrent writers.
There is no evidence that the history or receipt rows themselves need rewriting.
