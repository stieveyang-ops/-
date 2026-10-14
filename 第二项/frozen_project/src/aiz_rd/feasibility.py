"""AiZynthFinder QuickFilter feasibility features for Stage 3.

The project stores reactions in the forward ``precursors>>product`` direction,
while AiZynthFinder's QuickFilter consumes a :class:`RetroReaction` whose
target molecule is the product and whose reactants are the precursors.  This
module contains only that small, explicit adapter and the raw probability
calculation; it does not perform filtering or search.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from aizynthfinder.chem.mol import TreeMolecule
from aizynthfinder.chem.reaction import SmilesBasedRetroReaction


class ReactionReconstructionError(ValueError):
    """A frozen Stage-2 reaction could not be reconstructed as a retro reaction."""


class QuickFilterProbabilityError(ValueError):
    """The QuickFilter returned a non-finite or out-of-range value."""


class QuickFilterContractError(ValueError):
    """The probability and the loaded cutoff disagree about the boolean flag."""


class FeasibilityResult(NamedTuple):
    """Raw QuickFilter result and the frozen Stage-3 identity transform."""

    p_feas: float
    d_feas: float
    feasible_flag: bool
    filter_cutoff: float


def build_retroreaction_from_row(
    product_smiles: str,
    precursor_smiles: str,
    metadata: dict | None = None,
) -> SmilesBasedRetroReaction:
    """Build an AiZynthFinder-compatible retro reaction.

    Parameters are the Stage-2 project representation (``precursors>>product``
    split into its two sides).  The returned object represents ``product ->
    precursors`` and uses AiZynthFinder's own reaction/fingerprint semantics.
    """

    if not isinstance(product_smiles, str) or not product_smiles.strip():
        raise ReactionReconstructionError("product_smiles is empty/non-string")
    if not isinstance(precursor_smiles, str) or not precursor_smiles.strip():
        raise ReactionReconstructionError("precursor_smiles is empty/non-string")
    try:
        product = TreeMolecule(parent=None, smiles=product_smiles, sanitize=True)
        reaction = SmilesBasedRetroReaction(
            mol=product,
            index=0,
            metadata=dict(metadata or {}),
            reactants_str=precursor_smiles,
        )
        outcomes = reaction.reactants  # force AiZynthFinder's canonical adapter
    except Exception as exc:  # AiZynthFinder raises MoleculeException here
        raise ReactionReconstructionError(
            f"Could not construct retro reaction for product={product_smiles!r}, "
            f"precursors={precursor_smiles!r}: {exc}"
        ) from exc
    if not outcomes or len(outcomes) <= reaction.index or not outcomes[reaction.index]:
        raise ReactionReconstructionError("Retro reaction has no non-empty precursor outcome")
    return reaction


def compute_feasibility(
    product_smiles: str,
    precursor_smiles: str,
    quick_filter,
    metadata: dict | None = None,
) -> FeasibilityResult:
    """Return raw QuickFilter ``P_feas`` and ``D_F = 1 - P_feas``.

    ``quick_filter.feasibility`` is intentionally used instead of ``apply``:
    ``apply`` discards/raises on below-cutoff reactions and would introduce
    selection bias into this offline feature table.
    """

    reaction = build_retroreaction_from_row(product_smiles, precursor_smiles, metadata)
    try:
        feasible, probability = quick_filter.feasibility(reaction)
    except Exception as exc:
        raise QuickFilterProbabilityError(f"QuickFilter feasibility failed: {exc}") from exc
    try:
        p_feas = float(probability)
    except (TypeError, ValueError) as exc:
        raise QuickFilterProbabilityError(f"QuickFilter probability is not numeric: {probability!r}") from exc
    if not math.isfinite(p_feas) or not 0.0 <= p_feas <= 1.0:
        raise QuickFilterProbabilityError(f"QuickFilter probability outside [0,1]: {p_feas!r}")
    cutoff = float(quick_filter.filter_cutoff)
    expected_flag = p_feas >= cutoff
    if bool(feasible) != expected_flag:
        raise QuickFilterContractError(
            f"feasible flag {feasible!r} disagrees with p_feas={p_feas!r} and cutoff={cutoff!r}"
        )
    return FeasibilityResult(
        p_feas=p_feas,
        d_feas=1.0 - p_feas,
        feasible_flag=bool(feasible),
        filter_cutoff=cutoff,
    )
