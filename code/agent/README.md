# MS3 Agent core implementation

`ms3_agent.py` implements the fixed controller loop used to access a read-only
MS3 SQLite database. The permitted actions are:

1. `search_ms3`
2. `trace_paths`
3. `inspect_evidence`
4. `final`

The controller may issue at most six tool calls and may return a final answer
earlier. At the call limit, the runner requests a final answer. The deterministic
audit checks that final paper-specific citations were exposed and opened during
the trace; it is a provenance audit, not a semantic entailment verifier.

Supporting modules:

- `run_fig4_factorial.py`: API client, response normalization and audit helpers;
  the legacy filename is retained for compatibility with frozen run manifests.
- `run_structural_advantage_benchmark.py`: SQLite search and tokenization helpers.
- `EXPERT_REVIEW_RUBRIC.md`: complete blinded answer-evaluation instructions.
- `FS_EVIDENCEQA_REPORTING_RUBRIC.md`: concise release-facing definition of the
  published scores.

No API key is embedded. The runner reads the key from the environment variable
selected by `--api-key-env` (default: `DEEPSEEK_API_KEY`). The full database and
model service are not bundled in the public package. A small copyright-safe
database can be constructed with `code/demo/build_demo_db.py` to exercise the
three read-only tools without an API key. It demonstrates the interface only
and is not an evaluation corpus.
