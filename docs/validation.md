# Validation of the capture milestone

The eight capture tests check persisted snapshots after source edits and project
reopening, missing/tampered saved bytes, explicit historical gaps, parent links,
failed-capture cleanup, path restrictions, finite configurations, initialization
protection, and actual CLI JSON/error exits.

Five inspection tests check read-only operation before initialization, unchanged
files, extension-based capture proposals without invented relationships, excluded
directories and symlinks, real Git ignore behavior (including spaces/newlines),
Git revision capture, bounded traversal, and actual CLI validation/error exits.

Historical import has been validated locally using synthetic evidence: artifact
preservation across working-file edits and reopening, artifact tamper detection,
artifact-only imports, explicit unverified claims/gaps, rejection of missing or
duplicate paths and nonfinite claims, and CLI import/error exits. New regression
tests for import are being published in a separate follow-up commit; the current
repository suite still contains the thirteen capture/inspection tests.

Run against an installed package:

```bash
python -m pip install .
python -m unittest discover -s tests -v
researchledger --help
```

These tests do not execute research experiments. Source snapshots are not proof
of execution. The source-capture manifest is not a complete dependency inventory
or an authenticity signature. Python 3.12 was checked locally. GitHub CI for
Python 3.12 and 3.13 is planned; it has not run yet.
