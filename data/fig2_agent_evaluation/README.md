# Figure 2 reasoning-evaluation data

`benchmark_summary.csv` contains the complete aggregate matrix for the six
systems displayed in the manuscript. FS EvidenceQA additionally includes all
120 x 6 item--method numeric judgments, overall and subgroup summaries,
dimension-level subgroup scores and 10,000-replicate paired-bootstrap contrasts.

The frozen blind-evaluation archive contained a seventh system (LLaMat); it is
retained in the two annotated judgment JSON files but is not included in the
six-system manuscript table or `fs_evidenceqa_per_item_scores.csv`.

`matched_role_graph_ablation.csv` is a separate matched representation
experiment. It holds the controller, corpus and six-call budget fixed and should
not be merged as another method in the six-system comparison.

The final complete-set per-item archives for LitQA2, ScholarQA-CS2 and SciCUEval
were not recovered during release staging. Their aggregate frozen scores are
included; pilot-25 artifacts are not substituted. See
`../../docs/RELEASE_STATUS.md`.

Complete article excerpts, benchmark answer text and proprietary audit packets
are excluded from this public directory. The rubric, exact tool protocol and
code are in `../../code/agent` and `../../configs`.
