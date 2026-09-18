# FS EvidenceQA reporting rubric

This document records the scoring dimensions represented in the frozen blind
evaluation files. It is a release-facing rubric, not a verbatim model prompt.

Answers were randomly relabelled before evaluation. The evaluator received the
question, expert gold claims, unsupported-content boundaries and article audit
excerpts, but not the method identity, tool trace, runtime or token count.

Each dimension was scored from 0 to 4:

- **Scientific correctness**: accuracy of substantive scientific and quantitative
  claims relative to the audit packet.
- **Source groundedness**: extent to which substantive claims were supported by
  the supplied source evidence and identifiers.
- **Evidence completeness**: coverage of the evidence needed to answer the
  question without omitting central mechanisms, results, controls or limitations.
- **Boundary control**: correct separation of demonstrated, inferred, proposed and
  unreported content.

The prespecified composite is the unweighted mean of the four scores. Unsupported
substantive claims were counted separately. The frozen judgments also record the
most important error, a short justification and a within-case ranking. The main
figure reports six systems; the archived seven-system run additionally contained
LLaMat, which is not shown in the final comparison.

