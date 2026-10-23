# Meridian campus, maintenance planning desk

The six equipment rooms have accumulated separate as-built drawings. This
release requires a consolidated, auditable topology and a complete service
plan for three successive maintenance phases.

The drawing register `data/drawing_register.csv` lists the authoritative sheets.
They are legible original engineering-style schematics, not geographical maps.
Every cable has exactly two endpoints. Cable labels belong to the line they
are printed on. A crossing of lines is NOT a connection: only the labelled
node circles are terminations. No unlabelled splice or junction exists.
Sheet geometry and proximity have no electrical meaning.

Local sheets show within-room cables. The backbone sheet shows between-room
cables, terminating on the SAME node IDs shown on the local sheets. It does
not introduce extra intermediate nodes. Node IDs are globally unique.
All cables in the inventory are present exactly once in the drawing set.

Read `service-policy.md` for inventory selection, protection and capacity.
Read `output.md` for artifacts and execution. The activation budget is a real
authorization cap; choosing any valid plan under it is sufficient.

The inventory records cable characteristics, but is not an endpoint list.
The drawings, not a guessed naming pattern, are the endpoint source of record.
Include all cables in the transcription, even those that are not currently
usable or not selected for the maintenance plan.
