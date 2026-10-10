# Progressive development plan

Each milestone is implemented, verified, then committed with actual timestamps.
No prepared future code is replayed to manufacture a development history.

1. **Source capture:** package, SDK/CLI, explicit snapshots, parent relationships,
   provenance gaps, verification. Implemented.
   **Directory inspection:** bounded read-only file inventory, Git revision,
   exclusions and a reviewable capture proposal. Implemented before evidence
   import; semantic relationships and notebook execution analysis remain future work.
2. **Evidence import and export:** import mapped historical artifacts without
   inventing execution; portable manifests, evidence tables, missing-file reports.
   Explicit historical imports with artifact snapshots, declared claims and
   provenance gaps are implemented. Portable ZIP exports include verified saved
   bytes, metadata, evidence tables and explicit missing/changed-file reports.
3. **Local execution:** execute fixed snapshots/configurations, record environment,
   logs and outputs, distinguish failed/interrupted/unknown runs. Support existing
   lab allocations before automatic scheduler submission. Local Python execution,
   logs/output capture, failure/timeout/main-thread interruption handling and the
   synthetic numerical CPU example are implemented. Basic interpreter/platform
   metadata is captured; complete dependencies/environment restoration and abrupt
   crash reconciliation remain future work.
4. **Campaign constraints:** finite authorized experiment plans, scope versions,
   resource reservation, idempotency and crash reconciliation. No claim that
   arbitrary agent code is sandboxed or scientifically correct.
5. **ActionProof integration:** proper research-domain schemas and independent
   submission/effect observations, including concurrency and budget tests. Changes
   to ActionProof remain in its own repository.
6. **Research records and agent use:** versioned decisions and interpretations,
   artifact-linked documentation, reproducible evidence exports; agent use through
   the same interfaces as manual workflows.

First acceptance workflow: import a prior study with explicit gaps, capture and
run a small numerical experiment, preserve failures, inspect evidence and export
a bundle another researcher can understand. The same core must support a larger
model study without hardcoding its model, fitting method, or dataset.

## Repository boundaries

- This repository owns reusable capture, records, execution and exports.
- A research repository owns its scientific implementation and protocols.
- ActionProof owns authorization-testing abstractions and domain scenarios;
  this repository owns its executor adapter and integration fixtures.

## Initial architecture

SQLite is authoritative for record metadata. Captured bytes are stored separately
and identified by SHA-256. Generated documents will be views of records, not a
second writable source of experiment status. Configurations must contain finite
JSON values. Imported evidence and managed execution are distinct provenance
categories. Corrections must preserve the earlier record.

Open design work includes recovery after interruption, portable artifact storage,
execution environment capture, evaluator isolation and reliable job reconciliation.
Hashes identify bytes; they are neither backups nor proof of execution.

HPC execution is planned after a concrete local executor. A scheduler adapter
should preserve submitted snapshots/configurations, job identities and resource
requests, and reconcile scheduler status with logs and artifacts across chat
disconnects. Cluster scheduler, environments and storage must be inspected before
implementation. No HPC submission or monitoring exists in the current package.

## First usable workflow acceptance

The initial SDK/CLI workflow is implemented and locally validated by 42 tests
against source and installed package on Python 3.12.13/macOS; see
[validation](validation.md). The public example imports explicitly synthetic
historical-style evidence with gaps, runs a captured numerical CPU experiment,
preserves rejected-input failure evidence, revises a decision and exports saved
bytes with checked hashes. This is initial workflow acceptance, not a production
release, PyPI publication or scientific validation of a real study.

The user has authorized continued development toward the full SDK/CLI package.
Checkpoint resume for finalized local attempts is implemented: declared saved
checkpoints become verified inputs to new linked attempts. Experiment code owns
state restoration. Live checkpoint synchronization and abrupt-crash recovery
remain open. Remaining work includes:

- Durable live checkpoint capture/recovery and explicit compatible-output reuse
  to avoid wasted compute. Experiment code must save/restore its own state; resume attempts should
  verify compatibility and retain checkpoint/run lineage. Fresh replication must
  remain distinguishable from cached evidence.
- Reproducibility manifests for input versions, seeds and dependency/environment
  details, with explicit gaps and no guarantee of identical numerical outcomes.
- A general execution backend interface and scheduler adapters configured for
  different clusters, with durable job identities and duplicate-submission/crash
  reconciliation. Real cluster access is needed to validate a scheduler backend.
- Typed campaign scope/resource controls and independent ActionProof integration
  checks of submitted jobs and observed records. Neither is implemented.
- Richer project relationship proposals and artifact-linked documentation views.
- GitHub CI after workflow authorization, broader platform/version validation and
  package distribution. The saved workflow is not published or run.

The current ZIP is an evidence archive, not a restorable ledger or runnable
compute environment. Local execution is trusted Python execution, not isolation.
