# ResearchLedger

Keep research questions connected to the code and evidence behind them.

ResearchLedger is an early Python SDK and CLI for computational research using
scripts and Jupyter notebooks. It inventories project directories, captures
explicit source files and configurations, records provenance gaps, and verifies saved snapshots.
An agent and a researcher use the same Python or command-line operations.

**Current status: directory inventory, source capture and historical evidence import.** Recording a notebook does not execute
it, recover its kernel history, or establish that its contents produced a result.
Local Python execution is available; HPC execution and paper evidence exports are planned
in [the progressive roadmap](docs/roadmap.md).

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
`verify` currently checks experiment snapshots, not run logs/output snapshots.

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
