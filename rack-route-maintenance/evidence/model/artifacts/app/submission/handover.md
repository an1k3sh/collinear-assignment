# Meridian maintenance plan: handover

## Topology reconstruction
* I traced all nine registered sheets (rev 3) by machine using `extract_topology.py`. Its glyph OCR is in `ocr_lib.py` and uses the templates in `glyph_templates.json`.
* Wires are crisp 5 px strokes of a single colour. The tracer extracts the horizontal and vertical strokes. It joins two strokes only where one stroke's end meets another stroke's end at a right-angle bend, or across a collinear gap that contains a printed cable label. It never joins strokes that merely cross. A chain ends where a stroke touches a node box.
* Every stroke end had exactly one continuation. Every label pixel belonged to an in-line label. Each chain carried exactly one label, and all box names appear in `nodes.csv`. Local sheets contain only within-room cables, and spine sheets contain only between-room cables.
* Result: 87 cables (72 local, 15 backbone). They match the inventory L101–L187 one-to-one, with no duplicates, including blocked and unused cables.
* OCR check: the closest pair of glyph templates is 0.104 apart, so no character was ambiguous. I also traced room-A, spine-1 and spine-3 by eye, and every cable matched.

## Planning decisions
* Inventory: for each cable I used the latest record at or before the cutoff of 2026-06-15T08:00Z.
  * Records dated 09:00 are ignored, so L128 stays dark and L152 and L160 stay lit.
  * L119, L150 and L151 are blocked.
  * L103, L110 and L153 have capacity 6.
* Model: `build_plan.py` uses OR-Tools CP-SAT.
  * Each phase, service and role gets one directed flow path. Each node has at most one cable in and one cable out, so every route is a simple path.
  * Each cable's load is summed across all routes in both directions and kept within its capacity.
  * Outages remove cables for their phase only. Dark cables carry traffic only if they are in the global activation set.
  * Primary and secondary routes of each 1+1 service share no risk group.
* Objective: lowest activation spend first, then the fewest hops.
* Before writing its output, the planner checks the extracted routes again with a separate validator. That validator checks continuity, simple paths, usability, capacity, risk-group separation, completeness and the spend total.

## Cost
Six dark cables are activated: L104, L123, L138, L141, L154 and L162. They cost **10,000 cents**, within the budget of 36,000. The solver proved this is the lowest possible spend.

## Verification
* The planner runs in about 2 s and reports `OPTIMAL` with the plan validated.
* I copied the data and topology to another directory and ran the planner there. It again produced a valid plan with the same 10,000-cent spend. The routes can differ between runs because the solver uses several parallel workers.
* I checked that no phase uses a cable that is out of service in that phase (P1: L168/L112, P2: L173/L181, P3: L140/L156).
* Re-running `extract_topology.py` regenerates an identical `topology.json`.
