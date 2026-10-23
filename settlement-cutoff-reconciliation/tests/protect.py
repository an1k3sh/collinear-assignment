import hashlib
import json
from pathlib import Path

for name, expected in json.loads(Path("/tests/protected.json").read_text()).items():
    actual = hashlib.sha256((Path("/app") / name).read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f"Protected input changed: {name}")
