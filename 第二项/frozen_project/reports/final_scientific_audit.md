# Final scientific audit — Stage 11

Status: PASS for the frozen scientific definitions.

- No reaction-condition, yield, experimental-success, price, toxicity, environmental, SA-score, or free-form LLM chemistry feature was introduced.
- The production feature order remains exactly `[d_feas, d_prec, d_sc]`.
- `P_feas` is used only as model feasibility probability, never as experimental success probability.
- The frozen formulas, Stage 8 ordinal model, uncertainty thresholds, and Stage 9 route aggregation/ranking were not changed.
- Inference does not read expert labels, locked-test IDs, benchmark predictions, or perform fitting/refitting.
- AiZynthFinder MCTS/search rewards/UCB/backpropagation/expansion policy were not modified.
- Explanations are deterministic templates and do not infer conditions or yields.
