# Initial workflow validation

The repository suite contains 42 tests. All passed locally against both the
source checkout and the installed package on macOS with Python 3.12.13.
The installed CLI entry point was checked. CI and other platforms/Python versions
have not been validated; the saved GitHub workflow remains unpublished because
the current CLI authorization lacks workflow scope.

| Area | Tests | Evidence checked |
| --- | ---: | --- |
| Capture | 8 | Persisted snapshots after edits/reopening, tampering, gaps, parent links, cleanup, path restrictions and CLI exits |
| Inspection | 5 | Read-only inventory, bounded traversal, exclusions, Git ignore/revision and proposals without invented relationships |
| Historical import | 5 | Artifact bytes, explicit unverified claims/gaps, invalid mappings and CLI behavior |
| Execution | 5 | Actual snapshot/config execution, logs, failed/partial/missing outputs, timeouts and rejected paths |
| Run integrity | 4 | Log/output tampering, unresolved/legacy states, actual SIGTERM interruption and restored signal handlers |
| Export | 6 | Saved ZIP bytes and hashes, ancestor selection, historical gaps, partial exports and overwrite protection |
| Research records | 6 | Immutable/reopened revisions, invalid evidence, concurrent successor rejection, manual/agent declarations, CLI and export closure |
| Numerical workflow | 3 | Known quadrature error, actual success/failure records, decision revisions, every exported hash and destination preservation |

Run from the checkout root:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip install .
python -m unittest discover -s tests -v
researchledger --help
git diff --check
```

The CPU workflow uses a clearly labeled synthetic prior-result fixture and
computes a new trapezoidal estimate of the integral of x squared on [0, 1].
Its 8- and 64-interval estimates are checked against the analytic error
1/(6*n*n). A zero-interval request is rejected by input validation; its saved
request and error log remain linked to the failed run. Export checks inspect
records and actual ZIP member bytes, not just successful command exits.
No notebooks, GPU/cluster jobs or model APIs are executed by these tests.

This satisfies the bounded first usable workflow: explicitly import historical
style evidence with gaps, capture/run a numerical CPU experiment, preserve
failures, maintain versioned judgments and export portable evidence. It does not
validate a real historical study or arbitrary scientific workloads. Historical
claims and judgments remain declarations. Hashes do not establish authenticity,
scientific correctness, full dependency capture or code sandboxing.
Checkpoint/resume, automatic compute reuse, environment restoration, scheduler
reconciliation, campaign enforcement and ActionProof integration remain future work.
