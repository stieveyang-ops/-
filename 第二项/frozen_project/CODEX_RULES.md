# CODEX_RULES

1. Work incrementally. Complete and validate Stage 1 only.
2. Never modify files inside the installed AiZynthFinder package or its upstream source tree.
3. The project remains standalone package `aiz_rd`; AiZynthFinder is external.
4. Do not introduce reaction conditions, yield prediction, DFT, forward prediction, toxicity, price, environmental scores, SA score, RAscore, or extra ML descriptors.
5. The final scientific model is constrained to exactly `D_F`, `D_P`, `D_SC`.
6. Never call `P_feas` experimental success probability.
7. Do not generate synthetic weights, dummy policies, fake stock, fake SCScore weights, or fake RXNFP embeddings.
8. If a required model/dataset cannot be obtained from existing assets or explicitly allowed authoritative sources, STOP and report BLOCKED.
9. Do not substitute RXNFP with DRFP, Morgan, another fingerprint, or an LLM embedding.
10. Do not substitute AiZynthFinder QuickFilter with another feasibility model.
11. Do not substitute SCScore with SA score or another complexity score.
12. Do not silently impute missing values.
13. Do not silently upgrade an already working user environment.
14. Never delete or overwrite user data, models, or configuration without backup/diff and explanation.
15. Do not commit large weights, stocks, credentials, tokens, or secrets.
16. Record runtime paths, versions, hashes, and validation results.
17. Benchmark search must not use QuickFilter pruning; benchmark config must have no `filter:` section.
18. Production may contain QuickFilter; all non-filter settings must match benchmark.
19. Do not alter MCTS rewards, UCB, expansion priors, or route scoring in Stage 1.
20. Created scripts must be deterministic, explicit-error, and non-zero on failed mandatory checks.
21. No Stage-2 extraction or scoring in Stage 1.
22. RXNFP isolation is allowed only for the same official RXNFP model/package.
23. Stage-1 PASS requires real smoke tests for every mandatory component.
24. Run pytest and the full Stage-1 validation suite; stop if anything fails.
