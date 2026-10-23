# Meridian campus maintenance plan: handover

## Topology reconstruction (`topology.json`)

* I transcribed the nine register sheets at revision 3 (`room-A` to `room-F` and `spine-1` to `spine-3`)
  by reading each drawing. The result is 87 links: 12 within each room and 5 on each spine.
  Each link records the sheet it was taken from. Cable labels were assigned to the line they
  are printed on. Line crossings, including the three-line crossings at the centres of rooms
  A, B and E, were not treated as connections.
* I checked the transcription against the pixels:
  * For every node pair on every sheet, I measured dark-pixel coverage along the straight
    segment between the two nodes. All 87 claimed links scored 0.89–0.99. No unclaimed pair
    scored above 0.5.
  * Every blue label lies on exactly one claimed line, and every line carries a label.
* I also cross-checked the links against the data:
  * The cable set matches the 87 inventory cables exactly.
  * All endpoints appear in `nodes.csv`.
  * Every room-sheet link stays within its room, and every spine link joins two different rooms.

## Planning decisions (`build_plan.py`)

* **Inventory:** for each cable, the planner uses the latest record at or before the cutoff
  (`2026-06-15T08:00:00Z`). Records dated 09:00 are ignored. As a result:
  * L150, L151 and L119 are blocked.
  * L110 and L153 are lit with capacity 6.
  * L103 is dark with capacity 6.
  * L128 stays dark, L152 stays lit and L160 stays lit.
* **Model:** one CP-SAT model covers all three phases, so the activation list is shared.
  * Each phase, service and role has a unit flow on directed arcs. Each node has at most one
    incoming arc, which makes the walk from the source simple; any separate cycles are dropped.
  * Blocked and outaged cables are excluded. A dark cable can only be used if it is activated.
  * The load on each cable in each phase, summed over both directions and all routes,
    must not exceed its capacity.
  * The primary and secondary routes of each 1+1 service cannot share a risk group.
  * Total activation spend must stay within the budget.
* **Objective:** minimise activation cost first, then the total number of cable hops. The
  solver uses 4 workers with a 90 s limit and finishes in about 4 s.
* **Self-check:** before writing the output, the planner checks the plan with a separate
  validation routine and exits with an error if any check fails.

## Cost

The planner activates six dark cables: **L104, L123, L138, L141, L154 and L162**. Spend is
**10,000 cents** against a budget of 36,000. The solver proved this the minimum cost for the
transcribed topology. Lit cables are not charged, and each activation is charged once for the
whole maintenance window.

## Verification performed

* I ran the planner with the required command line. It returned OPTIMAL and its built-in
  validation passed.
* A separately written checker confirmed the following for every phase:
  * All 8 required service/role routes are present.
  * Every route is a simple path from source to target over consistent endpoints.
  * No route uses a blocked or outaged cable, or a dark cable that was not activated.
  * The 1+1 routes share no risk group.
  * Every cable's load is within its capacity. Peak utilisation is 100%, for example on
    L143 in P1 and L110 in P3.
  * The reported spend is correct.
* I reran the planner on a copy of the inputs in a different directory. Because the solver is
  multi-threaded, it produced a different route set, but the cost was the same (10,000) and
  the separate checker passed it too.
