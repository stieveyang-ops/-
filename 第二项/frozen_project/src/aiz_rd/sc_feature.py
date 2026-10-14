"""Raw AiZynthFinder SCScore features for one reaction step."""

from __future__ import annotations

import math
from typing import NamedTuple

from rdkit import Chem


class SCScoreValueError(ValueError):
    """A molecule could not be scored with the frozen SCScore implementation."""


class DeltaSCResult(NamedTuple):
    """Raw one-step SCScore values using the Stage-3 max definition."""

    sc_product: float
    sc_precursor_values: tuple[float, ...]
    sc_precursor_max: float
    delta_sc: float


class ReferenceDeltaSCResult(NamedTuple):
    """Audited reference-reaction ΔSC result for ECDF construction."""

    valid_for_ecdf: bool
    product_component_count: int
    product_smiles: str | None
    delta_sc: float | None
    sc_product: float | None
    sc_precursor_max: float | None
    exclusion_reason: str | None
    error_type: str | None
    error_message: str | None


def _parse_connected_components(side: str, side_name: str) -> list[str]:
    if not isinstance(side, str) or not side.strip():
        raise SCScoreValueError(f"{side_name} side is empty")
    components = [item.strip() for item in side.split(".") if item.strip()]
    if not components:
        raise SCScoreValueError(f"{side_name} side has no components")
    for component in components:
        try:
            molecule = Chem.MolFromSmiles(component, sanitize=True)
        except Exception as exc:
            raise SCScoreValueError(f"{side_name} component parse/sanitize failed for {component!r}: {exc}") from exc
        if molecule is None:
            raise SCScoreValueError(f"{side_name} component parse/sanitize failed for {component!r}")
    return components


def compute_reference_delta_sc(reaction_smiles: str, sc_model) -> ReferenceDeltaSCResult:
    """Apply the frozen single-connected-product reference rule.

    Multiple product components are deliberately excluded rather than reduced
    to a largest fragment or otherwise heuristically selected.
    """
    if not isinstance(reaction_smiles, str) or reaction_smiles.count(">>") != 1:
        return ReferenceDeltaSCResult(False, 0, None, None, None, None, "malformed_reaction", "ValueError", "reaction must contain exactly one >> separator")
    reactants, products = reaction_smiles.split(">>", 1)
    try:
        precursor_components = _parse_connected_components(reactants, "reactant")
    except Exception as exc:
        return ReferenceDeltaSCResult(False, 0, None, None, None, None, "reactant_parse_failed", type(exc).__name__, str(exc)[:500])
    if not isinstance(products, str) or not products.strip():
        return ReferenceDeltaSCResult(False, 0, None, None, None, None, "product_empty", "SCScoreValueError", "product side is empty")
    product_components = [item.strip() for item in products.split(".") if item.strip()]
    if not product_components:
        return ReferenceDeltaSCResult(False, 0, None, None, None, None, "product_empty", "SCScoreValueError", "product side has no components")
    # Parse every product component before counting; an unparseable component
    # is not silently ignored or treated as an agent.
    try:
        for component in product_components:
            molecule = Chem.MolFromSmiles(component, sanitize=True)
            if molecule is None:
                raise SCScoreValueError(f"product component parse/sanitize failed for {component!r}")
    except Exception as exc:
        return ReferenceDeltaSCResult(False, len(product_components), None, None, None, None, "product_component_parse_failed", type(exc).__name__, str(exc)[:500])
    if len(product_components) >= 2:
        return ReferenceDeltaSCResult(False, len(product_components), None, None, None, None, "multiple_products_undefined", None, None)
    product = product_components[0]
    try:
        result = compute_delta_sc(product, precursor_components, sc_model)
    except Exception as exc:
        return ReferenceDeltaSCResult(False, 1, product, None, None, None, "scscore_failed", type(exc).__name__, str(exc)[:500])
    return ReferenceDeltaSCResult(True, 1, product, float(result.delta_sc), float(result.sc_product), float(result.sc_precursor_max), None, None, None)


def ecdf_right_continuous(sorted_values, x: float) -> float:
    """Return ``#(delta <= x) / N`` using the fixed right-continuous rule."""
    import numpy as np

    values = np.asarray(sorted_values, dtype=np.float64)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all() or np.any(values[1:] < values[:-1]):
        raise ValueError("invalid sorted ECDF values")
    if not math.isfinite(float(x)):
        raise ValueError("query delta_sc must be finite")
    return float(np.searchsorted(values, float(x), side="right") / values.size)


def score_molecule_sc(smiles: str, sc_model) -> float:
    """Return the raw SCScore for one complete Stage-2 molecule representation."""

    if not isinstance(smiles, str) or not smiles.strip():
        raise SCScoreValueError("Empty/non-string molecule SMILES")
    try:
        rd_mol = Chem.MolFromSmiles(smiles, sanitize=True)
    except Exception as exc:
        raise SCScoreValueError(f"RDKit parse/sanitize failed for {smiles!r}: {exc}") from exc
    if rd_mol is None:
        raise SCScoreValueError(f"RDKit parse/sanitize failed for {smiles!r}")
    try:
        value = float(sc_model(rd_mol))
    except Exception as exc:
        raise SCScoreValueError(f"SCScore failed for {smiles!r}: {exc}") from exc
    if not math.isfinite(value):
        raise SCScoreValueError(f"SCScore is non-finite for {smiles!r}: {value!r}")
    return value


def compute_delta_sc(
    product_smiles: str,
    precursor_node_smiles: list[str],
    sc_model,
) -> DeltaSCResult:
    """Compute ``SC(product) - max_i SC(precursor_i)`` without normalization.

    ``precursor_node_smiles`` is deliberately a list of complete
    ReactionTree molecule nodes.  A dot inside one node is retained as part of
    that node and is never interpreted here as a node boundary.
    """

    if not isinstance(precursor_node_smiles, list) or not precursor_node_smiles:
        raise SCScoreValueError("At least one precursor molecule node is required")
    precursor_values = tuple(score_molecule_sc(item, sc_model) for item in precursor_node_smiles)
    product_value = score_molecule_sc(product_smiles, sc_model)
    precursor_max = max(precursor_values)
    delta = product_value - precursor_max
    if not math.isfinite(precursor_max) or not math.isfinite(delta):
        raise SCScoreValueError("SCScore-derived value is non-finite")
    return DeltaSCResult(
        sc_product=product_value,
        sc_precursor_values=precursor_values,
        sc_precursor_max=precursor_max,
        delta_sc=delta,
    )
