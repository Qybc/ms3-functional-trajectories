# Figure 3 innovation and historical-backtest data

The annual files describe how complete trajectories first appear and whether
they are re-observed within four years. Historical files preserve all four
rolling cutoffs, exact and system-validated closure endpoints, Top-K results,
average precision and the popularity-matched robustness analysis.

`strict_primary_trajectory_units.csv` is the 4,127-row derived input table for
the temporal analyses. `new_complete_trajectories_2022_2025_row_level.csv`
contains the 1,302 unique paths underlying the aggregate composition file and
the reported 1,021/1,302 (78.4%) result. These tables contain normalized fields
and bibliographic pointers, not publisher full text or long quotations.
`ranked_top100_candidates.csv` adds the 100 candidate paths selected by each of
the three relation-informed methods at each historical cutoff. Its endpoint
columns reproduce the reported exact and system-validated closure counts.

Candidate universes were frozen at the 2018–2021 cutoffs. The
`nested_structure_plus_evidence` rows are retrospective because that formulation
was refined after inspection of historical outcomes; they must not be described
as leakage-free prospective comparators. `role_agnostic` and `typed_structure`
remain the directly comparable cutoff-based rankings.

Random Top-100 expectations in `top100_closure_summary.csv` equal
`future_positives / candidate_universe x 100`. See `../../docs/DATA_DICTIONARY.md`
for field definitions and `../../code/historical_backtesting` for analysis code.
