# Evidence versions

These author-side files are not included in the agent image.

* `author/`, `harbor-oracle/`, and `v1-task-files.json`: original v1 author
  validation, before GROUP BY/HAVING were added.
* `v1-copilot/`: the user's passing v1 Opus/Copilot trial.
* `v2-author/`, `v2-harbor-oracle/`: validation of the expanded task before retry.
* `v2-frozen-files.json`: hashes of runtime files frozen for the v2 trial.
* `v2-copilot/`: passing v2 Opus/Copilot trial; its original reward is unchanged.
  `post-run-input-validity.json` is a separate measurement performed afterward.
* `v2-diagnostics-author/`, `v2-diagnostics-oracle/`: validation after the
  diagnostic-only extension.
* `current-task-files.json`: hashes of the currently packaged source/docs,
  excluding this evidence directory.

The current diagnostic extension changes verifier reporting, so its files
are not expected to match the frozen v2 verifier hashes. It does not change
the overall score formula or retroactively replace either model trial.
