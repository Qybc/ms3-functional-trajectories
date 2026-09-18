# Figure 2 reasoning-evaluation data

`benchmark_summary.csv` contains the complete aggregate matrix for the six
systems displayed in the manuscript. FS EvidenceQA additionally includes all
120 x 6 item--method numeric judgments, overall and subgroup summaries,
dimension-level subgroup scores and 10,000-replicate paired-bootstrap contrasts.

`matched_role_graph_ablation.csv` is a separate matched representation
experiment. It holds the controller, corpus and six-call budget fixed and should
not be merged as another method in the six-system comparison.

For LitQA2, ScholarQA-CS2 and SciCUEval, the shared release reports the
complete-set aggregate scores used in the manuscript. Item-level model outputs
are not included. The selected author-generated examples in this directory
illustrate the evaluation format alongside the aggregate full-set results.

Complete article excerpts, benchmark answer text and proprietary audit packets
are excluded from this public directory. The rubric, exact tool protocol and
code are in `../../code/agent` and `../../configs`.
