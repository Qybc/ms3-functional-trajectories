# MS3 dataset card

## Dataset summary

MS3 organizes literature on conductive-fibre flexible sensors as ordered
Material–Sensor–Signal–System trajectories. The frozen analysis snapshot contains
13,689 papers published from 2010 through the partial 2026 coverage period,
131,083 source-grounded evidence items, 26,648 complete or partial trajectory
records and 15,703 complete four-layer trajectories.

The corpus was constructed for mechanism reconstruction and historical analysis.
It is not a prevalence sample of the full flexible-sensor literature.

## Record structure

Each record separates:

- bibliographic metadata and a persistent paper identifier;
- paper-specific Material, Sensor, Signal and System terms;
- evidence items with role and source-location metadata;
- directed relations supported by those evidence items; and
- complete or partial trajectory objects. Missing layers and relations remain
  absent rather than being inferred.

The machine-readable structure is defined in
`schema/ms3_record.schema.json`. A copyright-safe example is provided in
`examples/ms3_record_example.json`.

## Construction and quality control

The extraction pipeline used three adapters over a shared Qwen2.5-72B-Instruct
backbone. Evidence alignment, node types, directed relations and evidence
references were checked deterministically before records entered downstream
analysis. A paper-disjoint set of 200 expert-annotated papers was reserved for
evaluation.

The held-out evaluation reported 99.6% evidence-source accuracy, 91.7%
completeness, 95.6% effective quality and 83.3% semantic full-path accuracy.
These metrics describe different failure modes and should not be collapsed into
a single accuracy claim.

## Public and controlled-access layers

This release contains aggregate and per-item numeric evaluation data needed for
the figures, historical backtest outputs, experimental source data and two
copyright-permitted trajectory tables: 4,127 strict paper--trajectory units and
the 1,302 unique complete trajectories supporting the 2022--2025 composition
analysis. It does not redistribute publisher PDFs, copyrighted figures, long
article excerpts, institutional-access acquisition scripts or API credentials.

The frozen full-text database and complete audit packets are retained by the
authors for editorial or reviewer inspection under controlled access. The
public trajectory tables contain normalized roles, bibliographic metadata and
source pointers while excluding restricted source content.

## Intended uses

- reproduce the numerical analyses and main-figure source data;
- inspect the MS3 record model and evidence-linking conventions;
- evaluate alternative ranking or reasoning methods on released numeric outputs;
- audit the distinction between demonstrated, inferred and missing relations.

## Out-of-scope uses

- estimating publication prevalence across all flexible-sensor research;
- treating a missing record as proof that no supporting publication exists;
- using trajectory ranks as an autonomous experimental or clinical decision;
- redistributing third-party full text or figures from the controlled corpus.

## Known limitations

Coverage depends on discoverability, full-text access, parsing quality and
terminology normalization. The 2026 interval is incomplete. Apparent gaps may
therefore reflect corpus coverage as well as untested scientific combinations.
Historical closure is defined at the normalized trajectory level and depends on
the chosen relation granularity. The two experimental studies test feasibility
at specified endpoints and do not establish general design optimality.

## Versioning

Files and SHA-256 checksums are listed in `manifests/MANIFEST.tsv`. Deposited
releases should be immutable and receive a persistent DOI. Corrections should be
issued as a new version with an explicit change log.
