# MS3 model and agent card

## Components

MS3 uses three task-specific QLoRA adapters over Qwen2.5-72B-Instruct:

- E-LoRA identifies source-aligned evidence items;
- T-LoRA assigns accepted evidence to paper-specific MS3 roles; and
- M-LoRA assembles supported roles and relations into complete or partial
  trajectories.

MS3-Agent operates over a read-only SQLite snapshot. It begins with an empty
workspace and can call three tools: `search_ms3`, `trace_paths` and
`inspect_evidence`. A run ends when the controller returns `final` or reaches the
six-tool-call ceiling. A deterministic post-run audit checks that paper-specific
citations refer to evidence opened during the run. The audit does not judge
semantic entailment and does not revise the answer.

## Training configuration

All adapters used 4-bit NF4 quantization with double quantization. LoRA targeted
the query, key, value and output projections with rank 16, scaling factor 16 and
dropout 0.05. Training used 14,000-token inputs, BF16 computation, gradient
checkpointing, DeepSpeed ZeRO-3, FlashAttention, cosine scheduling, zero weight
decay, maximum gradient norm 0.3 and seed 42. The effective batch size was 24
across three GPUs.

E-, T- and M-LoRA used 6,014, 5,344 and 5,346 training examples, respectively,
with 160 validation examples for each adapter. Learning rates were 1.5e-5,
1.0e-5 and 1.5e-5; inference used checkpoints 300, 220 and 220.

## Evaluation

Trajectory construction was evaluated on 200 paper-disjoint expert-annotated
papers. Reasoning was evaluated on the complete LitQA2-FullText (75 items),
ScholarQA-CS2 (100 items) and SciCUEval Materials (200 items) sets and on 120
expert-authored FS EvidenceQA questions. The final paper reports six systems.

The matched representation analysis replaced ordered MS3 records with an
unordered Role Graph while holding the controller, corpus and tool budget fixed.
It is a separate experiment from the six-system FS EvidenceQA comparison.

## Intended use

The agent is designed for evidence-grounded literature reasoning within the
frozen MS3 corpus. It can retrieve supported functional trajectories, inspect their
source evidence and abstain when the available records do not support a claim.

## Limitations and safety boundaries

- Output quality is bounded by corpus coverage and extraction accuracy.
- A valid citation identifier proves that evidence was opened, not that the final
  sentence is semantically entailed.
- The model can still omit evidence, combine incompatible contexts or overstate a
  relation. Human review remains necessary.
- Experimental candidates are decision support, not autonomous protocols. Domain
  experts retain responsibility for feasibility, ethics and safety.
- The released code does not include third-party model weights, service access or
  the restricted full-text database.

## Reproduction levels

Level 1 uses the public package to reproduce reported numerical summaries and
figures. Level 2 uses a compatible local MS3 SQLite database to test the tool
layer. Level 3 reruns language-model inference and additionally requires the
specified model endpoint and an API credential supplied through an environment
variable.
