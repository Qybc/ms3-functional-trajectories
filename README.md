# MS³ data and code

This repository accompanies **“Evidence-linked functional trajectories for
literature-driven scientific innovation.”** It contains the minimum data and
code needed to inspect the MS³ representation, verify the principal numerical
results and rebuild the Source Data and Supplementary Data workbooks.

Publisher full text and access-controlled literature databases are not
redistributed. Their absence does not affect the public checks described below.

## Quick start

```bash
python3 -m pip install -r requirements.txt
python3 code/demo/inspect_record.py examples/ms3_record_example.json
python3 code/analysis/reproduce_core_results.py .
python3 code/release/validate_release.py . --deep
```

The first two analysis commands use only released files. The deep validation
rebuilds both distributed Excel workbooks and compares their cells with the
archived versions.

To exercise the three read-only Agent tools without private data or an API key:

```bash
python3 code/demo/build_demo_db.py examples/ms3_record_example.json /tmp/ms3_demo.sqlite
python3 code/agent/ms3_agent.py --db /tmp/ms3_demo.sqlite \
  --tool-smoke-query "strain sensing" --output-dir /tmp/ms3_demo_output
```

## Repository contents

- `data/`: machine-readable data grouped by main figure.
- `source_data/`: Source Data workbook for Figs. 1–5.
- `supplementary_data/`: expanded benchmark and historical-backtesting tables.
- `code/analysis/`: compact, public-data-only checks of the central results.
- `code/agent/`: the bounded MS³ Agent controller, tool definitions and
  evaluation rubrics. Full inference requires a compatible literature database
  and a model endpoint.
- `code/historical_backtesting/`: the frozen analysis implementation used for
  the temporal evaluation. Public-data-only verification is provided separately
  in `code/analysis/`.
- `code/figure_data/`: data-preparation and plotting scripts for experimental
  panels.
- `code/release/`: workbook builders, integrity checks and archive utilities.
- `schema/` and `examples/`: the MS³ record schema and a copyright-safe example
  from which the local tool-demo database is built.
- `configs/`: frozen agent and evaluation definitions.
- `docs/`: installation, data dictionary, provenance and reproducibility notes.
- `manifests/`: file checksums and analysis provenance.

## What can be reproduced without restricted resources

The public package supports:

1. recalculation of the reported innovation-composition percentage;
2. inspection of complete-set benchmark summaries, the FS EvidenceQA item-level
   scores, paired bootstrap comparisons and the matched representation ablation;
3. verification of all four historical Top-100 evaluation windows from the
   released result tables;
4. rebuilding of the Source Data and Supplementary Data workbooks; and
5. inspection of the processed and raw experimental data distributed with the
   study.

Re-running literature extraction or live Agent retrieval requires source
articles, the frozen MS³ database and third-party model access. These resources
are not part of the public archive. The corresponding code is included to make
the implementation inspectable, not to imply that restricted inputs are
redistributed.

## Data and rights

The package contains author-generated numerical results, copyright-permitted
derived records and experimental data. It excludes publisher PDFs, long source
excerpts, copyrighted figures, institutional-access acquisition tools, API
credentials and third-party model weights. See `docs/PROVENANCE_AND_RIGHTS.md`
and `THIRD_PARTY_NOTICES.md`.

Repository and archival record:

- Repository: https://github.com/Qybc/ms3-functional-trajectories
- Archived release: https://doi.org/10.5281/zenodo.22826897 (reserved DOI;
  activated when the Zenodo record is published).

Author-owned source code is released under the BSD 3-Clause License in
`LICENSE`. Author-generated, redistributable data and documentation are released
under CC BY 4.0 as described in `LICENSE-DATA.md`. These licences do not apply to
the excluded third-party resources listed in `THIRD_PARTY_NOTICES.md`.

## Citation

Please cite the associated manuscript and the archived release. Repository
metadata, including the reserved archival DOI, are provided in `CITATION.cff`.
