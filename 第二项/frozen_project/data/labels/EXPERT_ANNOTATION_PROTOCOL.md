# EXPERT ANNOTATION PROTOCOL

Version: stage7_expert_annotation_protocol_v1

Judge each substrate-specific transformation using only the supplied structures
and your existing organic-synthesis knowledge. Exact conditions are unknown,
but reasonable conventional conditions may be selected. Do not use literature
searches or external databases for individual reactions.

Labels (write only the literal integer):
- 0 Easy: mature transformation/substrate combination, no major obstacle.
- 1 Medium: plausible but with meaningful structural, selectivity, or
  compatibility risk; some optimization is expected.
- 2 Difficult: uncommon or clearly challenging; substantial optimization or
  failure risk is expected.
- 3 Uncertain/Abstain: structure alone is insufficient for a responsible
  judgment. Do not guess.

Exclude price/availability, safety/toxicity/environment, yield, AiZynthFinder
route length/state score/rank, equipment, operator skill, and scale-up.
Annotate independently and do not discuss samples before submission. Do not
modify reaction_id, reaction_smiles, reactants, or product. Return exactly the
same five columns, with expert_label filled by 0/1/2/3 and no index column.
