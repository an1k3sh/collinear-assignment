# Scheduling desk handover

The source system exports complete VEVENT revisions into several files. File
order is a transport detail, not a revision order. Calendar namespaces are
separate even when feeds reuse UIDs.

The booking team needs an auditable list of the concrete appointments that
block each requested window and all feasible meeting slots for that window.
Expansion, revision selection and interval union must agree. The contracts
below deliberately define our supported subset rather than asking you to
implement the entire iCalendar standard.

Read `feed-contract.md` and `export-contract.md`. There is no undisclosed
provider-specific timezone definition, holiday calendar, workday restriction,
or inferred attendee policy.
