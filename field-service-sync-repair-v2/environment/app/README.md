# Field dispatch sync

Standard-library service plus a headless JavaScript client reducer, used by
handheld and desktop adapters. The fixture is synthetic, not production data.
`PROTOCOL.md` is the compatibility contract.

```
python3 tests/smoke.py
node --test tests/client-smoke.mjs
node client/trace.mjs < incidents/client-actions.json
python3 -m server.http --db state/site.sqlite --port 8080
python3 tools/repair.py --db state/site.sqlite
```

For a separate disposable incident database:
`python3 tools/seed.py --db /tmp/dispatch-copy.sqlite`.
The script deliberately refuses to overwrite an existing database.
