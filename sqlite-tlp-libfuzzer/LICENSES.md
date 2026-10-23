# External sources and licenses
## Task-specific provenance
New C++ task; adapts this exercise's earlier SQLite TLP schema and reference fixtures. TLP is published prior art.
Task-specific code, scenarios and fixtures were developed for this exercise, not copied from a public benchmark, issue, CTF or tutorial. Related revisions in this collection reuse components from the same exercise; they are not represented as independently invented scenarios. Detailed provenance and any conceptual references are in RUN_REPORT.md.
## Runtime and build distributions
* Python: [PSF license](https://docs.python.org/3/license.html), with bundled notices.
* Debian packages: package-specific licenses; installed copyright files are under `/usr/share/doc/*/copyright`. Container image and snapshot pins are in `environment/Dockerfile`.
* Harbor 0.24.0: [Apache-2.0](https://github.com/laude-institute/harbor/blob/main/LICENSE); external host runner, not copied task implementation.
* SQLite: [public domain](https://www.sqlite.org/copyright.html).
* LLVM/Clang/libFuzzer: [Apache-2.0 with LLVM exceptions](https://llvm.org/LICENSE.txt).
* nlohmann JSON: [MIT](https://github.com/nlohmann/json/blob/develop/LICENSE.MIT).
* CMake: BSD-3-Clause; Ninja: Apache-2.0. Package notices remain in the image.
* Conceptual prior art: [Ternary Logic Partitioning, OOPSLA 2020](https://doi.org/10.1145/3428279). The paper/SQLancer implementation is not copied.
* GitHub Copilot CLI, when used: official separately installed package under its upstream terms. Model inference requires an entitled account; no model weights or credentials are redistributed. Claude Code is also an external authenticated harness.

## Pinned Python dependencies
No third-party pip dependency is required by the task runtime; see Dockerfile for system packages and the detailed report for optional preparation tools.

Upstream license notices are retained. This inventory does not relicense third-party software. Installation resolves the pinned distributions; no external dataset is downloaded at solve time unless explicitly declared in the task policy.
