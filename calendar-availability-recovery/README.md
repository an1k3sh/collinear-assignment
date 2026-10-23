# Calendar availability recovery

A net-new offline booking exporter task grounded in the real problem of
reconciling independently delivered, versioned calendar feeds.

The incident includes 12 calendar namespaces, 24 transport files and five
publication windows. A reusable program must select current components,
expand finite recurrences, apply detached changes, produce auditable concrete
appointments, union their busy intervals and enumerate available meeting slots.

## Fairness and realistic difficulty

The public contract explicitly scopes the supported iCalendar subset rather
than implying full RFC compliance. It defines revision precedence, local-time
recurrence, invalid/ambiguous local times, elapsed versus nominal duration,
RDATE/EXDATE identity, detached instance changes, range changes and transparency.
The top-level instruction does not diagnose a particular bug.

Timezone transitions are real IANA data, pinned to tzdata 2025.2; PYTHONTZPATH
is empty so results do not depend on a host's zone database. No outside API,
holiday table, work-hours policy or hidden provider rule is needed.
The task allows two hours for the agent. Small verifier fixture runs allow
30 seconds each and require under a second for the oracle.

The economic outcome is avoiding double bookings and false unavailability.
An exporter can look right on normal days while losing or shifting an
appointment during a clock change or after a recurrence update.

## Independent verification

Thirty-three behavioral cases specify original and actual UTC instants
independently of the oracle. The reference never imports the oracle or uses
its recurrence expansion. It derives union/availability from these literal
golden intervals using endpoint partitioning. Timestamp formatting and list
ordering are normalized; equivalent offset timestamps are accepted.

The oracle independently implements recurrence/date expansion and component
state transitions. It passed all 35 criteria in a native Harbor container:
33 behavioral fixtures, the delivered multi-calendar incident, and protected
input/handover checks. Mutation controls test sensitivity to meaningful errors.
No LLM judge is used.

## Provenance and limitations

The source feeds, contracts, fixtures, expected instants, exporter and grader
were created from scratch for this exercise. They are not a port of a public
issue or benchmark. Timezone data and python-dateutil are declared external
libraries. Python is pinned by image digest.

The subset is intentionally finite and smaller than general iCalendar.
It does not include custom VTIMEZONE definitions, arbitrary BY* combinations,
floating provider policy or cancelled THISANDFUTURE ranges. These exclusions
are explicit in the public contract. Passing this task is not certification
of a production calendar engine.

## Reproduction

From the parent directory:

```sh
harbor run -p ./calendar-availability-recovery -a oracle
harbor run -p ./calendar-availability-recovery -a claude -m opus-5-5
harbor view ./jobs
```

The Claude Code command is the assignment recipe. The authorized experiment
uses Copilot CLI rather than Claude Code:

```sh
export PYTHONPATH="$PWD/calendar-availability-recovery/author"
# Supply valid Copilot authentication in the environment.
uvx --from harbor==0.24.0 harbor run -p ./calendar-availability-recovery \
  -a prototype_harness:PrototypeCopilot -m claude-opus-5.5 \
  --ak reasoning_effort=high --ak version=1.0.102 \
  --agent-setup-timeout-multiplier 5
```

The adapter changes only installation, using official checksum-verified Node
22.14.0 and official Copilot CLI 1.0.102 from npm. Harbor's Copilot execution
and trajectory processing remain inherited unchanged.
