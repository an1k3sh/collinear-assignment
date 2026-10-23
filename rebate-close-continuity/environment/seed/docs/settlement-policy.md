# Approved rebate policy, revision 4

## ERP event interpretation

`Events` has the columns event_id, revision, recorded_at, kind, line_id,
return_of, vendor, occurred_on, qty, unit, price, status.
Dates are ISO strings. Quantities/prices are decimal numbers; price is dollars
per invoiced unit. `unit` is PACK or EA. `Products` maps a purchase line's SKU
(stored in `Lines`) to units per pack and rebate eligibility.

For a given as-of date, first discard revisions recorded after that date.
For each event_id select the greatest numeric revision, NOT the last physical
row and NOT the latest occurred_on. Select revisions before checking status.
Identical replayed copies of an event revision count only once.
VOID means the entire selected event is excluded; it does not resurrect an
older ACTIVE revision. Ignore selected events occurring after the as-of date.
Every selected ACTIVE BUY has a unique line_id. Every selected ACTIVE RETURN
references an active BUY through return_of, even if that BUY is in a different
quarter. All supplied variations satisfy these referential constraints.

## Valuation, identity and accounting period

BUY quantity is in its invoiced unit. Convert quantities through Products when
necessary. A RETURN reverses the original BUY's unit economics, not its own
blank price/vendor, a current catalog price, or another invoice's price.
For example a BUY of 2 PACK at $19.99 per pack with 12 EA per pack has $39.98
gross; a RETURN of 1 EA reverses $19.99/12, rounded to $1.67.
For EACH event, round the extended dollar amount to cents with decimal
ROUND_HALF_UP, then apply a negative sign to returns. Do not round unit prices
before extending. An ineligible SKU has zero eligible cents, but still appears
in detail. Use the SKU of the referenced BUY for a return.

Both purchases and their returns belong to the original BUY's calendar quarter.
The original BUY's vendor and occurred_on select its group from `Aliases`;
intervals are [valid_from, valid_until), with an empty valid_until unbounded.
The return's date or the refresh date must never change that group/quarter.
Later revisions of a BUY replace its economics, date and vendor for ALL related
returns. A later return against Q1 restates Q1, rather than reducing Q2 purchases.

## Tier and journal rules

`Contracts` contains group, quarter, threshold_cents, rate_bps.
These are all-volume (retroactive), not marginal tiers: choose the row with
greatest threshold_cents <= max(0, net eligible cents). Exact equality qualifies.
Apply that one rate to the entire nonnegative net eligible amount.
All relevant group/quarters have a zero-threshold tier. Quarters are YYYY-Qn.
Entitlement dollars = ROUND_HALF_UP(net_cents * rate_bps / 1,000,000, 2).
The summary key set is the union of original BUY group/quarters represented in
current detail (including ineligible purchases) and keys in the prior approved
summary. Missing current amounts are zero; missing prior amounts are zero.

Adjustment = current entitlement minus previous APPROVED entitlement, not
minus the previous adjustment and not minus a just-refreshed current workbook.
Quarter/group sorting is not prescribed. Totals must not be treated as keys.

## Cutoffs and approvals

Turn 1 closes as of 2026-03-31 with no previous approved entitlement.
Turn 2 restates as of 2026-04-15 against frozen close-1.
Turn 3 rolls forward as of 2026-06-30 against frozen close-2.
The harness archives each delivered workbook before the next user turn. The
archive is an approved historical fact even if later revisions change Q1.
All active selected events through the cutoff appear in Detail, even if their
eligible cents are zero. No future or VOID event appears there.
