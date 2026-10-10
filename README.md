# ResearchLedger

Keep research questions connected to the code and evidence behind them.

ResearchLedger is an early Python SDK and CLI for computational research using
scripts and Jupyter notebooks. It inventories project directories, captures
explicit source files and configurations, records provenance gaps, and verifies saved snapshots.
An agent and a researcher use the same Python or command-line operations.

**Current status: inspection, capture, historical import, local execution, evidence export and versioned research records.** Recording a notebook does not execute
it, recover its kernel history, or establish that its contents produced a result.
Local Python execution and portable evidence export are available; HPC execution is planned
in [the progressive roadmap](docs/roadmap.md).

## Run the synthetic CPU workflow

After installing from this checkout, run:

```bash
python examples/cpu_workflow.py /tmp/researchledger-cpu-demo
researchledger --project /tmp/researchledger-cpu-demo runs
researchledger --project /tmp/researchledger-cpu-demo notes
researchledger --project /tmp/researchledger-cpu-demo verify
```

Choose a new destination; existing directories are refused. The example integrates
x squared on [0, 1] with two grid sizes using only the Python standard library.
It saves a bounded inventory and explicit capture plan, imports a clearly labeled
synthetic prior-result fixture with provenance gaps, executes captured sources,
retains logs and a request artifact when zero intervals is rejected, revises an
evidence-linked decision, verifies saved bytes, and writes `evidence.zip` plus a
readable `summary.json`. Results are computed during your run, not downloaded or
prebuilt. The example uses the same SDK operations exposed by the CLI; no agent
model API, GPU or cluster is required. Explicit checkpoint resume and declared-context output reuse are available for
finalized local runs. Fresh execution remains the default.

## Try the first milestone

Python 3.12 or newer. Install from this checkout; the package is not on PyPI.

```bash
python -m pip install .
```

Run the CLI from your research directory:

```bash
researchledger inspect --exclude 'private*'
researchledger init --name "Approximation study"
researchledger record --question "How does degree affect error?" \
  --source experiment.py --source experiment.ipynb \
  --config campaign.json --gap "Independent confirmation not yet run"
researchledger list
researchledger show exp-<identifier>
researchledger verify
```

`campaign.json` must contain a JSON object. Each `--source` is an explicit
project-relative file; directories are not scanned automatically. The config's
parsed values are stored in the record. Include it as a source too if you need
its exact original bytes. Commands emit JSON; invalid input and failed
verification exit nonzero. Use `researchledger --project /path/to/study ...`
to address another project.

## Inspect before capturing

`researchledger inspect` works before initialization and emits a JSON inventory
without writing a ledger or reading file contents. It classifies file extensions,
reports Git HEAD when available, and proposes source, configuration and artifact
candidates for your review. It does not establish which script produced a result.
JSON files are configuration candidates by extension; they may actually contain
results. The proposal does not automatically select or capture files.

The scan skips Git/ledger storage, common environment and cache directories,
dotenv paths, symlinks, Git-ignored paths when Git is available, and your repeatable
`--exclude` globs (matched against relative paths or entry names). It examines at
most 1,000 entries, including skipped paths and directories; use `--max-entries`
to change this limit. Check `complete`, `truncated`, and `warnings` before using a
report. A truncated scan may include different subsets as directory order changes.
Git ignore failures are reported; default and custom exclusions still apply.
This is an inventory, not a secret scanner, dependency graph, notebook execution
analysis, or atomic snapshot. Relationship inference is not implemented yet.

The same read-only operation is available in Python:

```python
from researchledger import inspect_project

report = inspect_project("/path/to/study", exclude=["private*"], max_entries=2000)
```

## Preserve historical evidence

After reviewing the directory inventory, explicitly map available source and
result files into a JSON manifest. For example, `history.json`:

```json
{
  "question": "What error was reported for degree three?",
  "sources": ["approximation.ipynb"],
  "artifacts": [{"path": "results/errors.csv", "role": "reported error table"}],
  "config": {"degree": 3},
  "claims": {"reported_max_error": 0.12},
  "context": {"study_label": "earlier exploratory run"},
  "gaps": ["Executed notebook version and calibration inputs unavailable"]
}
```

```bash
researchledger import --manifest history.json
researchledger verify
```

Python uses `project.import_history(manifest)` with the same JSON-compatible
object. File paths are relative to the research project, regardless of the
manifest's location. `sources` is optional when original code is unavailable;
at least one artifact with a declared `path` and `role` is required. All listed
files must exist; describe unavailable files in `gaps` rather than inventing
snapshots. Unknown manifest fields and nonfinite values are rejected. An optional
`parent` links an existing record; corrections create a new record.

Imported bytes are copied and hashed alongside source snapshots. `verify` checks
both kinds of saved file. Roles, configuration, context and claims are importer
declarations, not facts inferred from file contents. Every import retains
`execution_status: not_observed`, labels its claims `unverified_declaration`, and
adds an explicit execution/verification gap even if no other gaps are supplied.
Existing source-only records remain readable. Import does not parse result
tables, validate scientific claims, deduplicate repeated imports, or execute code.

## Use from Python

`researchledger note --manifest decision.json` appends a decision or interpretation.
The equivalent SDK operation is `project.add_research_record(manifest)`:

```json
{
  "kind": "decision",
  "statement": "Compare degree five next",
  "rationale": "The measured degree-three error exceeded the study target",
  "scope": "Synthetic approximation study on the sampled interval",
  "evidence": [{"record_id": "exp-<identifier>", "run_id": "run-<identifier>"}],
  "uncertainties": ["Sampled error does not bound error between sample points"],
  "origin": "manual"
}
```

Statement, rationale and scope are required; evidence references must exist and
runs must belong to the specified experiment. `kind` is `decision` or
`interpretation`; `origin` is `manual` or `agent`. A record without evidence is
allowed and remains an explicit unsupported declaration. No reasoning is inferred.
To revise a judgment, submit a complete new manifest with `supersedes` set to its
latest `note-<identifier>`; earlier versions remain unchanged. Each thread has one
linear revision history, and stale revisions are rejected. `researchledger notes`
lists all versions; `show-note note-<identifier>` reads one version. Python exposes
`project.research_records()` and `project.get_research_record(identifier)`.
Judgments remain `unverified_declaration`, even when they cite successful runs.
Selected exports include relevant whole revision threads and their referenced
experiments, in addition to experiment ancestors. Full exports include all judgments.


`researchledger export --output evidence.zip` bundles saved experiment records,
execution records, verified snapshots, logs and outputs. Use repeatable
`--record exp-<identifier>` to select experiments; parent records are included.
Python exposes `project.export("evidence.zip", record_ids=[record_id])`.
The ZIP contains `manifest.json` with hashes/issues, `records.json`, `runs.json`,
`research_records.json`, `evidence.csv`, and saved files. Missing/changed evidence is omitted and reported;
the bundle is still written, but the CLI exits nonzero. Existing destinations are
never overwritten. Live-run files and older unhashed logs are omitted with an
explicit gap. Export includes explicitly captured inputs, but excludes uncaptured external
inputs, dependency bytes and working directories, and is not a runnable environment or restorable ledger. Review its
contents before sharing; no redaction is performed.

Run a captured Python script with `researchledger run exp-<identifier>
--entrypoint experiment.py --output metrics.json --timeout 60`. The script runs
from a verified working copy using the CLI's Python interpreter. It can read
the stored configuration from the file named by `RESEARCHLEDGER_CONFIG`.
`researchledger runs` and `researchledger show-run run-<identifier>` read attempts.
Logs, working copies and declared output snapshots live in `.research/runs/`.
Python also supports `project.execute(record_id, "experiment.py",
outputs=["metrics.json"], timeout=60)`. Each attempt has its own run record;
the source record remains unchanged. A successful process with missing declared
outputs is marked `outputs_incomplete`. Failures and timeouts retain available
outputs and logs. Notebook execution and crash reconciliation are not implemented.
Execution inherits your environment and is **not a sandbox**. Run trusted code
only; neither exit status nor output hashes establish scientific correctness.
`verify` checks experiment snapshots plus finalized run logs, outputs and resume inputs.
Main-thread execution handles SIGINT/SIGTERM by stopping the process group and
recording the interruption. Abrupt crashes, SIGKILL, and worker-thread signals
can leave unresolved runs, which verification flags without guessing completion.
Older runs without log hashes report that verification gap; hashes are not
retroactively treated as if they were captured at execution time.

Capture data separately from executable sources:

```sh
researchledger record --question "Sum fixed observations" --source experiment.py --input data/values.json
researchledger run exp-<identifier> --entrypoint experiment.py --output metrics.json --dependency numpy
```

Python uses `project.record(..., inputs=["data/values.json"])` and
`project.execute(..., dependencies=["numpy"])`. Inputs must be explicit
project-relative files and follow the same path/storage exclusions as sources.
The ledger saves their bytes and hashes at capture time. Each run verifies them,
keeps a separate saved input copy and places a working copy at its original
relative path. Changes to the project's live data do not change that snapshot.
Input paths cannot also be outputs or executable entrypoints. New experiment
records are required for changed datasets. Verification and export include both
experiment input snapshots and saved run inputs.

`--dependency` is repeatable and names an installed Python distribution, rather
than an import module. Selected versions are observed from installed metadata
without importing package code; missing distributions and duplicate normalized
names are rejected. Repeat the same selection when resuming or reusing a run:
changed versions or selections are rejected. A package's version is not a hash of
its installed code. This does not record every transitive dependency, system
library, driver or environment variable, install dependencies, or enforce a seed.
Continue to declare these gaps and keep seeds in your experiment configuration.

Resume a finalized attempt using an explicitly declared checkpoint:

```sh
researchledger run exp-<identifier> --entrypoint experiment.py --checkpoint-output state.json --timeout 60
researchledger run exp-<identifier> --entrypoint experiment.py --checkpoint-output state.json --resume-from run-<identifier> --checkpoint state.json --timeout 60
```

In Python, pass `checkpoints=["state.json"]` to `project.execute`; to resume, also
pass `resume_from=prior_run["id"]` and `checkpoint="state.json"`. The script reads
its saved state from the path in `RESEARCHLEDGER_RESUME`, which is absent on fresh
runs. It must implement checkpoint saving and restoration itself, including any
model, optimizer, random generator and progress state its algorithm requires.
Write checkpoints atomically so interruption cannot leave a partial file.

The SDK captures declared checkpoint outputs when an attempt finalizes, including
handled failure, timeout or interruption. Resume verifies saved checkpoint bytes
and requires the same experiment snapshot, configuration, captured inputs,
entrypoint, arguments, selected dependency versions and basic interpreter/platform
identity. It creates a new attempt linked to the
prior run, saves the checkpoint as a verified input and includes it in exports.
This does not verify unselected dependencies, uncaptured external inputs or
checkpoint semantics.
Live checkpoint synchronization and recovery after SIGKILL or executor crashes
remain future work; only finalized attempts can be resumed.

Reuse completed output evidence explicitly, without launching another process:

```json
{
  "inputs": {},
  "dependencies": {"python": "stdlib-only"},
  "environment": {"algorithm": "integer-arithmetic"},
  "seed": null,
  "deterministic": true
}
```

Save this as `context.json`, declaring every relevant external input identity
(prefer a content hash), dependency version, environment setting and random seed.
Empty identity maps declare that no additional uncaptured external factors are relevant; `seed`
may be null for an algorithm without randomness. Do not put secrets in this file.
The context is a caller declaration, not an automatically verified environment.

```sh
researchledger run exp-<identifier> --entrypoint experiment.py --output metrics.json --reuse-context context.json
researchledger run exp-<identifier> --entrypoint experiment.py --output metrics.json --reuse-context context.json --reuse-from run-<identifier> --reuse-reason "Same deterministic calculation and declared inputs"
```

Python uses `project.execute(..., reuse_context=context)` on the original run;
subsequent requests also pass `reuse_from=prior_run["id"]` and `reuse_reason`.
Reuse requires a finalized successful original execution, identical experiment,
source/configuration, entrypoint, arguments, output/checkpoint declarations, basic
runtime identity, captured inputs, selected dependency versions and deterministic
context. All declared outputs must exist and
pass hash verification. Older runs without a context, failed/incomplete runs,
resumed runs and reuse records cannot serve as reuse sources in this version.

A reused request gets a new record with `status="reused"`, `execution_kind="reused"`,
prior-run lineage, reason and independently copied verified output evidence.
It has no process, execution start, return code or new execution logs. Verification
and portable exports include its saved outputs and distinguish it from computation.
A missing or changed output produces a failed preparation record; it never silently
launches a replacement experiment. Omit `reuse_from` to execute afresh for an
independent replication. No cache lookup, automatic freshness assessment or
scientific reproducibility guarantee is provided. The caller must assess untracked
state, nondeterminism and whether old evidence is appropriate for the current request.

```python
from researchledger import Project

project = Project.open(".")
record = project.record(
    question="How does degree affect error?",
    sources=["experiment.py"],
    config={"degree": 3},
    gaps=["Executed results have not been captured"],
)
print(record["id"])
```

Records persist in `.research/ledger.sqlite3`; explicit source copies live under
`.research/snapshots/`. Editing your working notebook does not replace a saved
snapshot. Parent IDs link follow-up records without modifying earlier records.
Keep your study's `.research/` directory out of public Git commits and back it up
with its snapshots. SQLite records alone do not preserve their files.

Capture excludes `.git`, `.research`, and dotenv paths. It is **not a secret
scanner**: inspect notebook outputs and explicitly selected files before sharing
them. Hash verification detects changed or missing snapshots, not malicious edits
to both the database and files, scientific errors, or missing undeclared imports.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
git diff --check
```

This project is general research infrastructure. Domain methods, datasets,
notebooks, and unpublished findings belong in separate research repositories.
ActionProof integration will test the future executor's authorization boundary;
it is not implemented in this milestone.

Development uses AI-assisted coding and review. Research claims require their
own evidence; this package does not establish publication readiness.
