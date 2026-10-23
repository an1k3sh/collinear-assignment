# Recover booking availability

The scheduling team has withheld publication of the availability export.
Rebuild it from the calendar feeds and requests in `/app/input`, using the
contracts in `/app/docs`.

Deliver:

* `/app/submission/rebuild.py`, run as
  `python /app/submission/rebuild.py --source /app/input --output /app/submission`;
* `/app/submission/bookings.json` and `/app/submission/availability.json`;
* `/app/submission/REPORT.md`, a concise handover covering the reconstruction
  and verification you performed.

The exporter must work for the complete supported feed format in the public
contract, not just the incident's particular timestamps. The verifier checks
the delivered exports and runs additional small calendar feeds within that
same contract. All required behavior and input bounds are documented.

Keep `/app/input` and `/app/docs` unchanged. Python, its standard library,
python-dateutil and pinned IANA time-zone data are available. No external service or network is
needed. Do not substitute a fixed list of appointments for the recurrence
and revision logic.
