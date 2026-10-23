# External sources and licenses
## Task-specific provenance
New synthetic business, workbook, requirements revision, oracle and verifier created for this exercise. No copied benchmark or external financial data.
Task-specific code, scenarios and fixtures were developed for this exercise, not copied from a public benchmark, issue, CTF or tutorial. Related revisions in this collection reuse components from the same exercise; they are not represented as independently invented scenarios. Detailed provenance and any conceptual references are in RUN_REPORT.md.
## Runtime and build distributions
* Python: [PSF license](https://docs.python.org/3/license.html), with bundled notices.
* Debian packages: package-specific licenses; installed copyright files are under `/usr/share/doc/*/copyright`. Container image and snapshot pins are in `environment/Dockerfile`.
* Harbor 0.24.0: [Apache-2.0](https://github.com/laude-institute/harbor/blob/main/LICENSE); external host runner, not copied task implementation.
* Node.js: [MIT and bundled component notices](https://github.com/nodejs/node/blob/main/LICENSE).
* LibreOffice: [MPL-2.0 and bundled component notices](https://www.libreoffice.org/about-us/licenses/).
* Fonts: Liberation and DejaVu distribution-specific OFL/Bitstream/other notices; consult the installed font packages' copyright files.
* GitHub Copilot CLI, when used: official separately installed package under its upstream terms. Model inference requires an entitled account; no model weights or credentials are redistributed. Claude Code is also an external authenticated harness.

## Pinned Python dependencies
| Dependency | Release license metadata | Used by |
|---|---|---|
| [et_xmlfile 2.0.0](https://pypi.org/project/et-xmlfile/2.0.0/) | MIT License | `environment/requirements.txt` |
| [openpyxl 3.1.5](https://pypi.org/project/openpyxl/3.1.5/) | MIT License | `environment/requirements.txt` |

Upstream license notices are retained. This inventory does not relicense third-party software. Installation resolves the pinned distributions; no external dataset is downloaded at solve time unless explicitly declared in the task policy.
