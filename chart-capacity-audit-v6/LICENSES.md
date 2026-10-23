# External sources and licenses
## Task-specific provenance
Original synthetic chart-only operations scenario; new data, revision history, counter resets, histograms and planning constraints. Extends this exercise's v1 exercise.
Task-specific code, scenarios and fixtures were developed for this exercise, not copied from a public benchmark, issue, CTF or tutorial. Related revisions in this collection reuse components from the same exercise; they are not represented as independently invented scenarios. Detailed provenance and any conceptual references are in RUN_REPORT.md.
## Runtime and build distributions
* Python: [PSF license](https://docs.python.org/3/license.html), with bundled notices.
* Debian packages: package-specific licenses; installed copyright files are under `/usr/share/doc/*/copyright`. Container image and snapshot pins are in `environment/Dockerfile`.
* Harbor 0.24.0: [Apache-2.0](https://github.com/laude-institute/harbor/blob/main/LICENSE); external host runner, not copied task implementation.
* GitHub Copilot CLI, when used: official separately installed package under its upstream terms. Model inference requires an entitled account; no model weights or credentials are redistributed. Claude Code is also an external authenticated harness.

## Pinned Python dependencies
| Dependency | Release license metadata | Used by |
|---|---|---|
| [contourpy 1.3.3](https://pypi.org/project/contourpy/1.3.3/) | BSD License | `author/requirements.txt` |
| [cycler 0.12.1](https://pypi.org/project/cycler/0.12.1/) | BSD License | `author/requirements.txt` |
| [fonttools 4.60.1](https://pypi.org/project/fonttools/4.60.1/) | MIT | `author/requirements.txt` |
| [kiwisolver 1.4.9](https://pypi.org/project/kiwisolver/1.4.9/) | BSD License | `author/requirements.txt` |
| [matplotlib 3.10.7](https://pypi.org/project/matplotlib/3.10.7/) | Python Software Foundation License | `author/requirements.txt` |
| [numpy 2.3.4](https://pypi.org/project/numpy/2.3.4/) | BSD License | `author/requirements.txt` |
| [packaging 25.0](https://pypi.org/project/packaging/25.0/) | Apache Software License; BSD License | `author/requirements.txt` |
| [pillow 12.0.0](https://pypi.org/project/pillow/12.0.0/) | MIT-CMU | `environment/requirements.txt` |
| [pyparsing 3.2.5](https://pypi.org/project/pyparsing/3.2.5/) | MIT | `author/requirements.txt` |
| [python-dateutil 2.9.0.post0](https://pypi.org/project/python-dateutil/2.9.0.post0/) | Apache Software License; BSD License | `author/requirements.txt` |
| [six 1.17.0](https://pypi.org/project/six/1.17.0/) | MIT License | `author/requirements.txt` |

Upstream license notices are retained. This inventory does not relicense third-party software. Installation resolves the pinned distributions; no external dataset is downloaded at solve time unless explicitly declared in the task policy.
