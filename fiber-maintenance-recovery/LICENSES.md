# External sources and licenses
## Task-specific provenance
Original fictional network, drawings, cable history, service requests, oracle and verifier; no public benchmark instance.
Task-specific code, scenarios and fixtures were developed for this exercise, not copied from a public benchmark, issue, CTF or tutorial. Related revisions in this collection reuse components from the same exercise; they are not represented as independently invented scenarios. Detailed provenance and any conceptual references are in RUN_REPORT.md.
## Runtime and build distributions
* Python: [PSF license](https://docs.python.org/3/license.html), with bundled notices.
* Debian packages: package-specific licenses; installed copyright files are under `/usr/share/doc/*/copyright`. Container image and snapshot pins are in `environment/Dockerfile`.
* Harbor 0.24.0: [Apache-2.0](https://github.com/laude-institute/harbor/blob/main/LICENSE); external host runner, not copied task implementation.
* GitHub Copilot CLI, when used: official separately installed package under its upstream terms. Model inference requires an entitled account; no model weights or credentials are redistributed. Claude Code is also an external authenticated harness.

## Pinned Python dependencies
| Dependency | Release license metadata | Used by |
|---|---|---|
| [Pillow 11.3.0](https://pypi.org/project/Pillow/11.3.0/) | MIT-CMU | `environment/requirements.txt` |
| [absl-py 2.3.1](https://pypi.org/project/absl-py/2.3.1/) | Apache-2.0 | `environment/requirements.txt` |
| [immutabledict 4.2.2](https://pypi.org/project/immutabledict/4.2.2/) | MIT | `environment/requirements.txt` |
| [numpy 2.2.6](https://pypi.org/project/numpy/2.2.6/) | BSD License | `environment/requirements.txt` |
| [ortools 9.14.6206](https://pypi.org/project/ortools/9.14.6206/) | Apache Software License | `environment/requirements.txt` |
| [pandas 2.3.3](https://pypi.org/project/pandas/2.3.3/) | BSD License | `environment/requirements.txt` |
| [protobuf 6.31.1](https://pypi.org/project/protobuf/6.31.1/) | 3-Clause BSD License | `environment/requirements.txt` |
| [python-dateutil 2.9.0.post0](https://pypi.org/project/python-dateutil/2.9.0.post0/) | Apache Software License; BSD License | `environment/requirements.txt` |
| [pytz 2025.2](https://pypi.org/project/pytz/2025.2/) | MIT License | `environment/requirements.txt` |
| [six 1.17.0](https://pypi.org/project/six/1.17.0/) | MIT License | `environment/requirements.txt` |
| [typing_extensions 4.15.0](https://pypi.org/project/typing_extensions/4.15.0/) | PSF-2.0 | `environment/requirements.txt` |
| [tzdata 2025.2](https://pypi.org/project/tzdata/2025.2/) | Apache Software License | `environment/requirements.txt` |

Upstream license notices are retained. This inventory does not relicense third-party software. Installation resolves the pinned distributions; no external dataset is downloaded at solve time unless explicitly declared in the task policy.
