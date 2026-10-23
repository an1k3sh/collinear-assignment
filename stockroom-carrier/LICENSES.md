# External sources and licenses
## Task-specific provenance
New synthetic language, implementation, fixtures and tests created for this assignment; not a port of a public benchmark.
Task-specific code, scenarios and fixtures were developed for this exercise, not copied from a public benchmark, issue, CTF or tutorial. Related revisions in this collection reuse components from the same exercise; they are not represented as independently invented scenarios. Detailed provenance and any conceptual references are in RUN_REPORT.md.
## Runtime and build distributions
* Python: [PSF license](https://docs.python.org/3/license.html), with bundled notices.
* Debian packages: package-specific licenses; installed copyright files are under `/usr/share/doc/*/copyright`. Container image and snapshot pins are in `environment/Dockerfile`.
* Harbor 0.24.0: [Apache-2.0](https://github.com/laude-institute/harbor/blob/main/LICENSE); external host runner, not copied task implementation.
* GitHub Copilot CLI, when used: official separately installed package under its upstream terms. Model inference requires an entitled account; no model weights or credentials are redistributed. Claude Code is also an external authenticated harness.

## Pinned Python dependencies
No third-party pip dependency is required by the task runtime; see Dockerfile for system packages and the detailed report for optional preparation tools.

Upstream license notices are retained. This inventory does not relicense third-party software. Installation resolves the pinned distributions; no external dataset is downloaded at solve time unless explicitly declared in the task policy.
