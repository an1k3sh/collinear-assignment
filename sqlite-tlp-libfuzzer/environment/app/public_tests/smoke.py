import json
from pathlib import Path
import subprocess
import sys

cli = str(Path(sys.argv[1]).resolve())
requests = [{"op": "inspect", "hex": b.hex()} for b in (b"", b"\0", bytes(range(128)))]
case = {"version": 1, "source": "single", "mode": "rows",
        "tables": {"t": [[1, 0, 8, "q'"], [2, 0, -3, "x\0y"], [3, None, None, None]],
                   "u": []},
        "predicate": ["gt", ["col", "t", "v"], ["lit", 0]], "where": None,
        "select": [["col", "t", "v"]], "value": None, "group_by": []}
requests.append({"op": "case", "case": case})
result = subprocess.run([cli], input="".join(json.dumps(r)+"\n" for r in requests),
                        text=True, capture_output=True, check=True)
answers = [json.loads(line) for line in result.stdout.splitlines()]
assert len(answers) == len(requests)
for answer in answers:
    assert answer["result"]["calls"] == 4
    assert answer["result"]["equivalent"]
    assert len(answer["plan"]["parts"]) == 3
assert answers[-1]["result"]["base"] == [[8], [-3], [None]], "stored data must survive insertion"
print("Three byte inputs and a hand-calculated database witness passed; not an exhaustive test.")
