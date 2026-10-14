"""Post-search AiZynthFinder 4.4.1 scorer integration."""
from __future__ import annotations

from typing import Any

from aizynthfinder.context.scoring import Scorer
from aizynthfinder.reactiontree import ReactionTree

from .chemistry import canonicalize_reaction, reaction_hash
from .route_ranker import RouteDifficultyEvaluator


class ReactionDifficultyScorer(Scorer):
    scorer_name = "reaction ease score"

    def __init__(self, config=None, evaluator=None, difficulty_by_hash=None,
                 uncertainty_by_hash=None, **kwargs):
        super().__init__(config=config)
        self.evaluator = evaluator
        self.difficulty_by_hash = difficulty_by_hash or {}
        self.uncertainty_by_hash = uncertainty_by_hash or {key: 0.0 for key in self.difficulty_by_hash}
        self._reverse_order = True

    def _score_reaction_tree(self, tree: ReactionTree) -> float:
        if self.evaluator is not None and not self.difficulty_by_hash:
            result = self.evaluator.score_reaction_tree(tree)
            if not result.difficulty_applicable:
                raise ValueError("Cannot assign reaction difficulty to a zero-reaction route")
            return 1.0 - float(result.difficulty_bottleneck) / 100.0
        rows = []
        for reaction in tree.reactions():
            key = reaction_hash_from_tree_node(tree, reaction)
            if key not in self.difficulty_by_hash:
                # Frozen route analysis uses canonical reaction hashes.  The
                # scorer smoke test may provide an explicit tree map instead.
                raise KeyError(f"no frozen difficulty for reaction {key}")
            rows.append({"step_id": str(key), "reaction_smiles": str(reaction.smiles),
                         "reaction_difficulty": float(self.difficulty_by_hash[key]),
                         "uncertainty": float(self.uncertainty_by_hash[key])})
        if not rows:
            raise ValueError("Cannot assign reaction difficulty to a zero-reaction route")
        evaluator = self.evaluator or RouteDifficultyEvaluator(0.0, 1.0)
        result = evaluator.score_route_steps(__import__("pandas").DataFrame(rows))
        if not result.difficulty_applicable:
            raise ValueError("Cannot assign reaction difficulty to a zero-reaction route")
        return 1.0 - float(result.difficulty_bottleneck) / 100.0

    def _score_node(self, node: Any) -> float:
        return self._score_reaction_tree(node.to_reaction_tree())

    def __repr__(self) -> str:
        return self.scorer_name


def reaction_hash_from_tree_node(tree: ReactionTree, reaction: Any) -> str:
    """Recover the canonical forward reaction represented by a tree node."""
    product = str(reaction.mol.smiles)
    precursor_nodes = list(tree.graph.successors(reaction))
    precursors = [str(node.smiles) for node in precursor_nodes]
    _, _, canonical = canonicalize_reaction(precursors, product)
    return reaction_hash(canonical)
