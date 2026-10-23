# Release the campus fiber maintenance plan

Network operations needs an executable maintenance plan for the fictional
Meridian campus. The current as-built connectivity is recorded in the PNG
drawings under `/app/drawings`; cable inventory, service requirements and the
work sequence are under `/app/data`. Read `/app/docs/brief.md` and its linked
operating documents.

Deliver under `/app/submission`:

* `topology.json`: a complete machine-readable transcription of the as-built
  cable endpoints.
* `maintenance.json`: the activated cables and service routes for every phase.
* `build_plan.py`: a reproducible offline planner, run as
  `python /app/submission/build_plan.py --data /app/data --topology /app/submission/topology.json --output /app/submission/maintenance.json`.
* `handover.md`: a concise description of the reconstruction, planning
  decisions, cost and verification performed.

Formats and requirements are in `/app/docs`. Deliver every service throughout
every phase, preserve the specified protection, respect capacity and keep
activations within the authorized budget. A globally optimal or unique plan is
not required.

Do not change `/app/data`, `/app/docs` or `/app/drawings`. OR-Tools, Pillow,
NumPy and standard Python are installed. You may inspect or crop the drawings
with any available tool. There is no hidden topology file to locate and no
external information is needed.
