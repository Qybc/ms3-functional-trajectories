# Data dictionary

## File-level index

| Directory | File | Unit of observation |
|---|---|---|
| `data/fig1_framework` | `corpus_scale.csv` | Corpus inventory measure |
|  | `trajectory_connectivity.csv` | Trajectory completeness class |
|  | `evidence_grounding.csv` | Evidence-grounding profile |
|  | `extraction_evaluation.csv` | Extraction method--metric pair |
| `data/fig2_agent_evaluation` | `benchmark_summary.csv` | Benchmark--method aggregate |
|  | `fs_evidenceqa_method_summary.csv` | Method aggregate over 120 cases |
|  | `fs_evidenceqa_subgroups.csv` | Task-type--method aggregate |
|  | `fs_evidenceqa_dimension_subgroups.csv` | Task-type--method--dimension aggregate |
|  | `fs_evidenceqa_paired_bootstrap.csv` | Paired MS3 contrast |
|  | `fs_evidenceqa_per_item_scores.csv` | Case--method judgment |
|  | `matched_role_graph_ablation.csv` | Matched-ablation metric |
| `data/fig3_innovation_backtesting` | `annual_composition.csv` | Year--innovation mode |
|  | `new_complete_trajectories_2022_2025.csv` | Novelty class |
|  | `new_complete_trajectories_2022_2025_row_level.csv` | Unique complete trajectory first observed in 2022--2025 |
|  | `strict_primary_trajectory_units.csv` | Strict paper--trajectory observation used by temporal analyses |
|  | `four_year_reobservation.csv` | Innovation-mode endpoint |
|  | `nested_metrics.csv` | Cutoff--endpoint--ranking method |
|  | `top100_closure_summary.csv` | Top-100 cutoff--endpoint--method summary |
|  | `ranked_top100_candidates.csv` | Cutoff--ranking method--ranked Top-100 candidate |
|  | `popularity_matched_metrics.csv` | Popularity-matched method summary |
|  | `popularity_matched_pairs.csv` | Matched positive--negative trajectory pair |
| `data/fig4_conductive_network` | `representative_five_cycle_traces.csv` | Architecture--strain--display point |
| `data/fig5_cardiac_interface` | `tensile_adhesion_selected_groups.csv` | Group--displacement point |
|  | `peel_selected_groups.csv` | Group--displacement point |
|  | `extension_resistance.csv` | Strain--resistance point |
|  | `cyclic_resistance_envelope.csv` | Cycle window |
|  | `porcine_ecg_display_points.csv` | Condition--time display point |
|  | `porcine_heart_rate_display_points.csv` | Condition--time display point |

## Fig. 2 FS EvidenceQA

- Scores range from 0 to 4 for scientific correctness, source groundedness,
  evidence completeness and boundary control.
- `composite_0_4` is the unweighted mean of these four dimensions.
- `normalized_percent` is `composite_0_4 / 4 × 100`.
- `unsupported_claim_count` is the blinded evaluator's count for the response.
- Full response text and the source packets are not required to reproduce the
  plotted numeric comparisons and are not included in the public package.
- `audit_packet_adequate` is the evaluator's binary judgment that the supplied
  article audit excerpts were sufficient for scoring.
- `positive_items`, `tied_items` and `negative_items` count questions on which
  the MS3 composite was greater than, equal to or less than the comparator.
- `first_place_count` counts cases tied for or holding the highest composite
  within a blinded case; `mean_rank` retains ties from the frozen evaluation.

## Fig. 3 historical backtesting

- `strict_primary_trajectory_units.csv` contains 4,127 strict original-research
  paper--trajectory observations. It contains normalized roles and bibliographic
  pointers, but no publisher full text or long source excerpts.
- `new_complete_trajectories_2022_2025_row_level.csv` contains the 1,302 unique
  paths underlying the headline composition result. The `mode` field partitions
  them into 1,021 higher-order recombinations, 140 Material implementation
  cases, 78 transduction-novelty cases, 28 application-transfer cases and 35
  multi-layer cases. `mask` records novelty at the three adjacent relations in
  Material-to-System order.

- `closed_in_future` requires exact normalized trajectory closure in later original
  research with non-reference evidence for all adjacent relations.
- `validated_closure` additionally requires system-level validation in the stated
  application.
- `nested_structure_plus_evidence` is retrospective because its formulation was
  refined after inspection of the historical outcomes.
- Random Top-100 expectation is `future_positives / candidate_universe × 100`.
- `hits_at_K` is the number of future-positive trajectories among the first `K`
  ranked candidates; `precision_at_K = hits_at_K / K`.
- `selected_evidence_composite`, `selected_fusion_mode` and `selected_weight`
  record the frozen ranking configuration. They do not convert the retrospective
  structure-plus-evidence analysis into a prospective comparator.
- Popularity-matched pairs contain one future-positive and one future-negative
  candidate matched on node-popularity bins; each `*_win` field is a binary
  indicator that the method ranked the positive member higher.
- `ranked_top100_candidates.csv` contains 1,200 rows: four cutoffs, three
  relation-informed rankings and ranks 1--100. Its two endpoint columns
  reproduce every Top-100 closure count in the summary table.

## Fig. 4 conductive-network traces

- `cycle_sequence` concatenates three independently selected five-cycle windows in
  ascending strain order; it is not continuous elapsed time.
- `delta_R_over_R0_percent` is derived from the first-percentile resistance within
  each representative raw window, matching the figure-generation code.
- Three devices were tested per architecture; the main figure displays one
  representative device per architecture.

## Fig. 5 cardiac-interface data

- The long-cycle envelope is the 5th and 95th resistance percentile in consecutive
  nominal 10-cycle windows.
- ECG display points are min/max-preserving decimated values from three 30-s,
  1-kHz windows in one acute porcine recording.
- Heart rate is the acquisition system's ECG-derived channel displayed as a centred
  6-s moving median sampled every 0.25 s.
- The two-animal study is descriptive; one representative segment per condition is
  shown in the main figure.
- `relative_time_fraction` maps each displayed condition window to 0--1 for panel
  alignment; `relative_time_s` preserves seconds within the selected window.
- `source_file`, `source_block`, `source_start_s` and `source_stop_s` identify the
  retained acquisition segment. They are provenance fields, not biological
  replicates.
- `smoothing` records the heart-rate display transformation. ECG display values
  are min/max-preserving decimated points rather than a new filtered signal.

## Missing values and units

Blank cells mean unavailable or not applicable; they are not silently imputed.
Percentages are expressed on a 0--100 scale unless a field explicitly contains a
fraction. Electrical resistance is in ohms, tensile adhesion in kPa, peel
strength in N m⁻¹, displacement in mm, ECG amplitude in mV and heart rate in
beats min⁻¹. File-specific headers retain the unit where practical.
