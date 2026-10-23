# Recover the morning dispatch

The depot manager has withheld release of today's cold-chain dispatch. Produce
an executable replacement from the operating records in `/app/data` and the
rules in `/app/docs`. Start with `docs/handover.md`.

Deliver these files in `/app/submission`:

* `plan.json`: the reconciled order state, stock allocations, packing schedule,
  vehicle trips and spend, in the format in `docs/output.md`.
* `build_plan.py`: a reproducible offline program that reads the supplied inputs
  and writes the plan. Run it as
  `python /app/submission/build_plan.py --data /app/data --output /app/submission/plan.json`.
* `dispatch-note.md`: a concise operational handover explaining the reconciliation,
  key scheduling decisions, spend and checks you performed.

The plan must fulfill every dispatchable order, obey every operating constraint,
and stay within the authorized spend. Every timeline entry uses integer minutes
after 08:00 local time. You may use the installed OR-Tools solver or any other
installed tools. No external data or network is needed.

Do not modify `/app/data` or `/app/docs`. There is no requirement to find a unique
or globally optimal plan. The verifier checks outcomes, not a particular
algorithm or trip order. It also reruns your program against identical input
files in a different directory and checks that the generated plan is valid.
