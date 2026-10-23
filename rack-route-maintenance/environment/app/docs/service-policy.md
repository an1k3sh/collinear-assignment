# Network operations rules

## Inventory state

The cutoff is in `data/settings.json`. `cable_versions.csv` contains complete
versioned records keyed by `cable`. Select the greatest `recorded_at` that is
at or before the cutoff. Records after that cutoff are not known.

The selected status is `lit`, `dark` or `blocked`. Lit cables are available
without activation. Dark cables can be used only if included in the single
global `activate` list. Blocked cables cannot be used or activated. Activation
does not change physical endpoints, capacity, risk group or phase outages.

Every cable has a positive integer `capacity` in traffic units, a `risk_group`
and an integer `activation_cents`. Charge activation once per selected dark
cable for the entire window, even if used in several phases. Do not charge
lit cables. The sum cannot exceed `budget_cents`.

## Maintenance phases

`phases.csv` lists the phases. A cable listed for a phase in `outages.csv` is
unusable throughout that phase, whether lit or activated. The phases are
successive, not concurrent; capacity is checked separately per phase.
You may change service routes between phases without additional charge.

## Services and routing

`services.csv` gives `service`, `source`, `target`, positive integer `units`
and `protection`. Every service is required in every phase.

Each route is an ordered list of cable IDs describing a simple undirected
path from that service's source to target. Direction is inferred by walking
from the source. No repeated cable or repeated node is allowed. There are no
other port, transit-node, latency or hop-count constraints.

For `protection=none`, deliver one route named `primary`.
For `protection=1+1`, deliver both `primary` and `secondary`. The two routes
must share NO `risk_group`, not merely no cable. Endpoints and intermediate
nodes may be shared; the declared protection concerns cable failure domains,
not node failures. Risk group IDs are global across the campus.

Both copies of a 1+1 service transmit all the time. Each consumes the FULL
`units` on every cable of its own path. For every cable and phase, sum the
units from ALL routes of ALL services using that cable, in either direction.
This shared undirected load must not exceed the selected cable capacity.
There is no shared standby capacity, directional capacity doubling, traffic
splitting or use of intermediate service endpoints as new demands.

An outage in one risk group may remove at most one route of each protected
service. No additional simultaneous-failure guarantee is required.
