"""Run good/bad controls against the same verifier, without altering the task."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


CONTROLS = {
    "receipt_scope": ("server/store.py",
                      '"SELECT * FROM receipts WHERE tenant=? AND device=? AND mutation=?",\n'
                      '                (tenant, device, mutation)',
                      '"SELECT * FROM receipts WHERE tenant=? AND mutation=?",\n'
                      '                (tenant, mutation)'),
    "missing_digest_check": ("server/store.py",
                             'if receipt["digest"] != fingerprint:', 'if False:'),
    "partial_commit": ("server/store.py",
                       '            if self.fault:\n                self.fault("after_document")',
                       '            db.commit()\n            if self.fault:\n'
                       '                self.fault("after_document")'),
    "moving_snapshot": ("server/store.py",
                        'cut = decimal(item["cut"], "invalid_cursor")', 'cut = head'),
    "inclusive_pull": ("server/store.py", 'tenant=? AND seq>? AND seq<=?',
                       'tenant=? AND seq>=? AND seq<=?'),
    "unsafe_number": ("client/replica.mjs", 'return BigInt(value);', 'return Number(value);'),
    "clear_later_edits": ("client/replica.mjs", 'p.mutation !== ack.mutation',
                          'p.id !== ack.record.id'),
    "receipt_checkpoint": ("client/replica.mjs",
                           "receive(state, ack.record, state.snapshot?.epoch ?? state.epoch);",
                           "receive(state, ack.record, state.snapshot?.epoch ?? state.epoch);\n"
                           "      state.checkpoint = ack.record.seq;"),
    "lost_staged_push": ("client/replica.mjs",
                         "if (number(record.seq) > number(state.snapshot.cut)) merge(state.snapshot.buffer, record);",
                         "/* post-cut record not retained */"),
    "merge_snapshot": ("client/replica.mjs", "state.base = stage.rows;",
                        "state.base = {...state.base, ...stage.rows};"),
    "late_persistence": ("client/durable.mjs",
                         "  await save(path, sending);\n  const response = await exchange(sending.pending[0].wire);",
                         "  const response = await exchange(sending.pending[0].wire);"),
    "incomplete_repair": ("server/store.py", '            db.execute("DELETE FROM documents")',
                          '            db.execute("DELETE FROM documents WHERE deleted=1")'),
    "batch_partial_commit": ("server/store.py",
                             "                    responses.append(self._mutate(",
                             "                    db.commit()\n                    responses.append(self._mutate("),
    "ignore_confirmations": ("client/replica.mjs",
                             "function confirm(state, confirmations) {",
                             "function confirm(state, confirmations) { return;"),
    "batch_rounded_revision": ("client/replica.mjs",
                               "String(number(base) + 1n)", "String(Number(base) + 1)"),
    "late_batch_persistence": ("client/durable.mjs",
                               "  await save(path, sending);\n  const response = await exchange(sending.batch.wire);",
                               "  const response = await exchange(sending.batch.wire);"),
}


def main():
    output = Path("/logs/controls")
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    variants = {"good_json_format": ("server/codec.py", "ensure_ascii=False", "ensure_ascii=True"),
                **CONTROLS}
    for name, (relative, old, new) in variants.items():
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "app"
            shutil.copytree("/app", app)
            file = app / relative
            source = file.read_text()
            if source.count(old) != 1:
                raise AssertionError(f"Control target is not unique: {name}")
            file.write_text(source.replace(old, new))
            logs = output / name
            process = subprocess.run(
                ["python3", "/tests/grade.py"], capture_output=True, text=True, timeout=120,
                env={**os.environ, "APP_ROOT": str(app), "VERIFIER_LOG": str(logs)})
            logs.mkdir(parents=True, exist_ok=True)
            (logs / "process.log").write_text(process.stdout + process.stderr)
            reward = json.loads((logs / "reward.json").read_text())
            expected = 1.0 if name.startswith("good_") else 0.0
            results[name] = {"reward": reward, "expected_overall": expected,
                             "correct_classification": reward["overall"] == expected}
            print(name, reward["overall"], "expected", expected, flush=True)
    (output / "summary.json").write_text(json.dumps(results, indent=2))
    if not all(result["correct_classification"] for result in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
