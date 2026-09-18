# Reproducibility guide

## 1. Recalculate the central reported values

From the release root, run:

```bash
python3 code/analysis/reproduce_core_results.py .
```

This public-data-only check recalculates the reported innovation-composition
percentage directly from 1,302 row-level trajectories, cross-checks its
aggregate table, and verifies the complete-set benchmark summaries, FS EvidenceQA method means and
the Top-100 historical results for all four cutoffs. It requires neither an API
key nor the restricted literature database.

## 2. Validate the archive

From the release root, run:

```bash
python3 code/release/validate_release.py .
```

The validator checks manifest hashes, required files, benchmark row counts,
Source Data workbook readability and key cross-file totals.

`manifests/RUN_PROVENANCE.json` links the principal benchmark, historical and
experimental result files to their analysis scope and frozen SHA-256 hashes.

## 3. Inspect the MS3 record model

```bash
python3 code/demo/inspect_record.py examples/ms3_record_example.json
```

The demonstration uses only the Python standard library. It prints the ordered
trajectory, supported relations and evidence pointers from a copyright-safe
illustrative record.

## 4. Inspect numerical source data

`source_data/MS3_Source_Data_v1_20260918.xlsx` contains one sheet for each main
figure or analysis block. Sheet names begin with the corresponding figure number.
The README sheet records units and display transformations.

`supplementary_data/MS3_Supplementary_Data_1_benchmark_audit_v1_20260918.xlsx`
contains the expanded evaluation and historical-audit tables used by reviewers.
It is generated from the CSV and JSON sources by
`code/release/build_supplementary_data.py`.

The expanded CSV files in `data/` are convenient for scripted analysis. In
particular:

- Fig. 2 contains benchmark summaries, 120-question FS EvidenceQA scores,
  paired bootstrap results and the matched representation ablation;
- Fig. 3 contains all four rolling-origin windows and both closure endpoints;
- Fig. 3 also contains the 4,127 strict paper--trajectory units and the 1,302
  row-level trajectories underlying the innovation-composition result;
- Figs. 4 and 5 contain the electrical, adhesion and physiological display data
  underlying the plotted panels.

## 5. Recreate figure-data products

Install the lightweight numerical dependencies:

```bash
python3 -m pip install -r requirements.txt
```

The scripts under `code/figure_data/` accept local inputs or use files colocated
with the release. Generated SVG files should be written to a separate working
directory so that the immutable release remains unchanged.

The Supplementary Data workbook can be rebuilt independently:

```bash
python3 code/release/build_supplementary_data.py \
  --output /tmp/MS3_Supplementary_Data_1.xlsx
```

The main Source Data workbook can likewise be rebuilt from the released CSVs:

```bash
python3 code/release/build_source_data.py \
  --output /tmp/MS3_Source_Data_rebuilt.xlsx
```

## 6. Run the agent tool layer

The following level requires a compatible, read-only SQLite database:

```bash
python3 code/agent/ms3_agent.py \
  --db /path/to/ms3.sqlite \
  --tool-smoke-query "strain sensing under large deformation" \
  --output-dir /tmp/ms3_tool_smoke
```

Full inference additionally requires a model endpoint and an API credential. No
credential is stored in the release. Use the command-line options documented by
`python3 code/agent/ms3_agent.py --help`.

## 7. Restricted inputs

The publisher-derived full-text corpus cannot be redistributed publicly.
Re-running extraction and live retrieval therefore requires author-controlled
inputs in addition to the code supplied here. The released result tables and
public verification script remain sufficient to check the numerical claims
listed in Sections 1–5.
