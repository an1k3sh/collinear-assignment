# Output contract

`topology.json`:

```json
{"links":[{"cable":"L001","a":"A01","b":"A02"}]}
```

There must be exactly one entry per drawn cable. `a`/`b` may be exchanged,
and link order is irrelevant. Node and cable identifiers are case-sensitive.
Additional fields are permitted. The example is only a format illustration.

`maintenance.json`:

```json
{
  "activate":["L001"],
  "activation_cents":1000,
  "phases":[
    {"phase":"P1","routes":[
      {"service":"S1","role":"primary","cables":["L001","L002"]},
      {"service":"S1","role":"secondary","cables":["L003","L004"]}
    ]}
  ]
}
```

Include exactly the phases and required service/role combinations specified
in the inputs. No duplicate activation, phase, or service/role entry.
Arrays may be reordered except the cable list within a route.
Report the correct integer activation spend. No chosen path is prescribed.

The planner must read the supplied inventory, work sequence, service records
and transcribed topology, and write the requested output. It may use
intermediate files alongside that output. For grading it is rerun on identical
input contents copied to a different directory, with a 180-second allowance
on the declared four-CPU environment. Your exploratory runs may take longer.
The supplied topology argument is the submitted transcription, not a secret
reference graph. Regeneration must produce another valid plan.
