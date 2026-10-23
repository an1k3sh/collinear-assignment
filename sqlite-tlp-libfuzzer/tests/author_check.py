"""Rebuild and fully grade correct alternatives and deliberately faulty C++ variants."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def replace_once(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new, 1)


def variants(engine, generator):
    yield "oracle", engine, generator, 1.0
    yield "alternative-wrapper", replace_once(engine, "        return q;",
          '        q.sql = "SELECT * FROM (" + q.sql + ")";\n        return q;'), generator, 1.0
    yield "alternative-row-order", replace_once(engine, "    return {base, combined, equivalent};",
          "    std::reverse(base.begin(), base.end());\n"
          "    std::reverse(combined.begin(), combined.end());\n"
          "    return {base, combined, equivalent};"), generator, 1.0
    yield "ignored-input", engine, replace_once(generator, "    Random r(bytes);",
          "    (void)bytes;\n    Random r(std::vector<uint8_t>{1,2,3});"), 0.0
    yield "prefix-only", engine, replace_once(generator, "    Random r(bytes);",
          "    Random r(std::vector<uint8_t>(bytes.begin(), bytes.begin() + "
          "(bytes.size() < 8 ? bytes.size() : 8)));"), 0.0
    helper = replace_once(generator, "Json generate(const std::vector<uint8_t>& bytes)",
                          "Json generated_case(const std::vector<uint8_t>& bytes)")
    assert helper.endswith("}\n}\n")
    helper = helper[:-2]
    for name, seed in (("literal-data-only", "std::vector<uint8_t>{1,2,3}"),
                       ("catalogue-32", "std::vector<uint8_t>{static_cast<uint8_t>("
                        "bytes.empty() ? 0 : bytes[0] % 32)}")):
        modified = helper + (
            "Json generate(const std::vector<uint8_t>& bytes) {\n"
            f"    auto c = generated_case({seed});\n"
            '    c["tables"] = generated_case(bytes)["tables"];\n'
            "    return c;\n}\n}\n")
        yield name, engine, modified, 0.0
    yield "group-bag-union", replace_once(engine,
          '    if (mode == "rows" || mode == "having") return rows;',
          '    if (mode == "rows" || mode == "having" || mode == "group") return rows;'), generator, 0.0
    yield "having-set-union", replace_once(engine,
          '    if (mode == "rows" || mode == "having") return rows;',
          '    if (mode == "having") { std::map<std::string, Row> unique;\n'
          '        for (const auto& row : rows) unique[key(row)] = row;\n'
          '        rows.clear(); for (const auto& item : unique) rows.push_back(item.second); }\n'
          '    if (mode == "rows" || mode == "having") return rows;'), generator, 0.0
    yield "average-of-averages", replace_once(engine,
          "            else value = static_cast<double>(total) / static_cast<double>(count);",
          "            else { double sum = 0; int n = 0;\n"
          "                for (const auto& state : item.second.second) if (state[1] != 0) {\n"
          "                    sum += state[0].get<double>() / state[1].get<double>(); ++n; }\n"
          "                value = sum / n; }"), generator, 0.0
    yield "null-as-zero", replace_once(engine, "        Json value = nullptr;",
                                       "        Json value = 0;"), generator, 0.0
    yield "left-as-inner", replace_once(engine, 'source == "left" ? " LEFT JOIN" : " JOIN"',
                                       'source == "left" ? " JOIN" : " JOIN"'), generator, 0.0
    yield "ignore-where", replace_once(engine, 'if (!c.at("where").is_null())',
                                     'if (false && !c.at("where").is_null())'), generator, 0.0
    yield "omit-unknown", replace_once(engine, 'return "((" + p + ") IS NULL)";',
                                     'return "((" + p + ") IS NULL AND 0)";'), generator, 0.0
    yield "always-success", replace_once(engine, "    bool equivalent = equal(base, combined);",
                                         "    bool equivalent = true;"), generator, 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    app = out / "app"
    shutil.copytree(root / "environment/app", app, dirs_exist_ok=True)
    engine = (root / "solution/engine.cpp").read_text()
    generator = (root / "solution/generator.cpp").read_text()
    entries = list(variants(engine, generator))
    entries.append(("baseline", (root / "environment/app/src/engine.cpp").read_text(),
                    (root / "environment/app/src/generator.cpp").read_text(), 0.0))
    summary = {}
    for name, cpp, gen, expected in entries:
        if args.only and name not in args.only:
            continue
        (app / "src/engine.cpp").write_text(cpp)
        (app / "src/generator.cpp").write_text(gen)
        log = out / name
        env = dict(os.environ, APP_ROOT=str(app), VERIFIER_LOG=str(log),
                   ASAN_OPTIONS="detect_leaks=1:quarantine_size_mb=32",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        result = subprocess.run([sys.executable, str(root / "tests/verify.py")],
                                env=env, text=True, capture_output=True, timeout=550)
        (out / (name+".log")).write_text(result.stdout + result.stderr)
        reward = json.loads((log / "reward.json").read_text())
        details = json.loads((log / "details.json").read_text())
        assert details["checks"]["build"], f"{name}: mutation must build to be an informative control"
        summary[name] = {"reward": reward, "expected": expected, "exit": result.returncode}
        (out / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        print(name, json.dumps(reward), flush=True)
        assert reward["overall"] == expected and (result.returncode == 0) == (expected == 1), name
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
