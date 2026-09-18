# Installation and demonstration

## System requirements

The public validation and demonstration utilities require Python 3.9–3.12 and
run on macOS, Linux or Windows without non-standard hardware. The package was
tested for submission on macOS with Python 3.9.6, NumPy 2.0.2, SciPy 1.13.1 and
openpyxl 3.1.5. Supported dependency ranges are listed in `requirements.txt` and
`environment.yml`.

The full agent requires two resources that are not bundled: a compatible
read-only MS3 SQLite database and access to the configured language-model
endpoint. GPU hardware is not required for the public archive checks or example
record.

## Installation

With conda:

```bash
conda env create -f environment.yml
conda activate ms3-release
```

Alternatively:

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python3 -m pip install -r requirements.txt
```

Creating the lightweight environment typically takes a few minutes, depending
on network and package caches.

## Demonstration 1: inspect an evidence-linked trajectory

```bash
python3 code/demo/inspect_record.py examples/ms3_record_example.json
```

Expected output:

```text
paper_id: P_EXAMPLE_001
M1: conductive composite on a deformable fibre scaffold -> strain-sensitive conductive network -> relative resistance change -> motion-monitoring demonstrator
  supported relations: Material->Sensor, Sensor->Signal, Signal->System
  evidence chain: E1, E2, E3
validation: PASS
```

The command uses only the Python standard library and completed in less than one
second in the submission test environment.

## Demonstration 2: recalculate the central results

First recalculate the central numerical results from the released CSV files:

```bash
python3 code/analysis/reproduce_core_results.py .
```

The command ends with `verification: PASS` and requires no optional dependency,
API key or private database.

## Demonstration 3: exercise the read-only Agent tools

Build a one-record, copyright-safe database and run the same three tool actions
used by the full Agent:

```bash
python3 code/demo/build_demo_db.py \
  examples/ms3_record_example.json /tmp/ms3_demo.sqlite
python3 code/agent/ms3_agent.py \
  --db /tmp/ms3_demo.sqlite \
  --tool-smoke-query "strain sensing" \
  --output-dir /tmp/ms3_demo_output
```

This demonstration does not call a language model. It checks search, trajectory
inspection and evidence opening against synthetic, copyright-safe content.

## Demonstration 4: validate the complete archive

From the release root:

```bash
python3 code/release/validate_release.py .
```

The validator checks required files, workbook structure, benchmark dimensions,
example-record references and every manifest checksum. A successful run ends
with `validation: PASS`. The check completed in less than one second in the
submission test environment, excluding file download or archive extraction.

For a cell-level reconstruction check of both Excel workbooks, run:

```bash
python3 code/release/validate_release.py . --deep
```

The deep check rebuilds Source Data and Supplementary Data in a temporary
directory and compares every cell with the distributed workbooks.

## Rebuild Supplementary Data 1

```bash
python3 code/release/build_supplementary_data.py \
  --output /tmp/MS3_Supplementary_Data_1.xlsx
```

This command reconstructs the reviewer-facing workbook from the released CSV
and JSON files. It neither calls a model nor accesses publisher content.

## Rebuild Source Data

```bash
python3 code/release/build_source_data.py \
  --output /tmp/MS3_Source_Data_rebuilt.xlsx
```

This command reconstructs all 23 Source Data sheets from CSV files contained in
the public archive. It requires no private corpus, model endpoint or raw project
directory.

## Full agent invocation

With a compatible database, the read-only tool layer can be checked using:

```bash
python3 code/agent/ms3_agent.py \
  --db /path/to/ms3.sqlite \
  --tool-smoke-query "strain sensing under large deformation" \
  --output-dir /tmp/ms3_tool_smoke
```

Full inference additionally requires an API credential supplied through the
environment variable selected by `--api-key-env`. Do not place credentials in
source files, command history or the release archive. If the local workflow must
open PDF files, first install the optional parser dependencies:

```bash
python3 -m pip install -r requirements-agent.txt
```
