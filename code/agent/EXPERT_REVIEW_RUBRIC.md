# FS EvidenceQA blinded evaluator instructions

Review every response without attempting to infer the method that produced it.
Responses within a case answer the same question and are judged against the same
expert gold claims, unsupported-content boundaries and article audit excerpts.
Method identity, tool trace, runtime and token count are hidden during scoring.
Fluency alone is not evidence of scientific correctness.

## Scored dimensions

### Scientific correctness (0–4)

- **4**: all substantive scientific and quantitative claims are correct.
- **3**: the central answer is correct with one minor, non-consequential error or
  omission.
- **2**: the central direction is plausible but the answer contains a material
  error or major omission.
- **1**: the answer is mostly incorrect, with only isolated correct content.
- **0**: the answer is incorrect, irrelevant, non-responsive or presents
  unsupported content as fact.

### Source groundedness (0–4)

- **4**: every substantive claim is directly supported by the supplied evidence.
- **3**: almost all substantive claims are supported; one link is weak or
  indirect.
- **2**: support is mixed or several evidence links do not entail their claims.
- **1**: most claims are unsupported or attributed to mismatched evidence.
- **0**: evidence is fabricated, unavailable or unrelated to the answer.

### Evidence completeness (0–4)

- **4**: the answer covers the central mechanisms, results, controls and limits
  required by the question without irrelevant material.
- **3**: one minor supporting element is missing.
- **2**: one major mechanism step, result, control or limitation is missing.
- **1**: only a small fraction of the necessary evidence is covered.
- **0**: no usable evidence is provided.

### Evidence-boundary control (0–4)

- **4**: consistently distinguishes demonstrated, inferred, proposed and
  unreported content and abstains where evidence is insufficient.
- **3**: boundaries are correct except for one minor ambiguity.
- **2**: at least one important claim is assigned to the wrong evidence status.
- **1**: proposals, demonstrations and missing evidence are repeatedly conflated.
- **0**: the response shows no usable boundary control.

## Additional records

Count unsupported substantive claims separately. Record the most important error
and a concise justification for each score. After scoring all blinded responses
within a case, rank them from best to worst and state whether the supplied audit
packet was adequate for evaluation. The prespecified composite is the unweighted
mean of the four 0–4 dimensions.

The release-facing summary of these instructions is
`FS_EVIDENCEQA_REPORTING_RUBRIC.md`. Frozen numeric judgments and two annotated
examples are included in Supplementary Data 1.
