from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aizynthfinder.reactiontree import ReactionTree

from .chemistry import canonicalize_reaction, reaction_hash


class RouteTopologyError(ValueError):
    pass


@dataclass(frozen=True)
class SerializedReaction:
    product_raw: str
    precursors_raw: tuple[str, ...]
    metadata: dict[str, Any]
    reaction_depth: int
    original_serialized_index: int


def count_serialized_reactions(route: dict[str, Any]) -> int:
    count = 0
    def visit_mol(node: dict[str, Any]) -> None:
        nonlocal count
        children = node.get("children", [])
        for rxn in children:
            if rxn.get("type") != "reaction":
                raise RouteTopologyError("Molecule child is not a reaction node")
            count += 1
            for precursor in rxn.get("children", []):
                visit_mol(precursor)
    visit_mol(route)
    return count


def _serialized_reactions(route: dict[str, Any]) -> list[SerializedReaction]:
    found: list[SerializedReaction] = []
    traversal = 0
    def visit_mol(node: dict[str, Any], molecule_depth: int) -> None:
        nonlocal traversal
        if node.get("type") != "mol" or not node.get("smiles"):
            raise RouteTopologyError("Invalid molecule node")
        for rxn in node.get("children", []):
            traversal += 1
            if rxn.get("type") != "reaction":
                raise RouteTopologyError("Expected reaction child")
            precursors = rxn.get("children", [])
            if not precursors:
                raise RouteTopologyError(f"Reaction under {node['smiles']} has no precursor child")
            raw = tuple(str(child.get("smiles", "")) for child in precursors)
            if any(not item for item in raw):
                raise RouteTopologyError("Precursor molecule has empty SMILES")
            found.append(SerializedReaction(str(node["smiles"]), raw, rxn.get("metadata", {}), molecule_depth + 1, traversal))
            for child in precursors:
                visit_mol(child, molecule_depth + 2)
    visit_mol(route, 0)
    return found


def extract_route_rows(target_id: str, route_index: int, route: dict[str, Any]) -> list[dict[str, Any]]:
    rebuilt = ReactionTree.from_dict(route)
    serialized = _serialized_reactions(route)
    reconstructed_count = len(list(rebuilt.reactions()))
    if len(serialized) != reconstructed_count:
        raise RouteTopologyError(f"Reaction topology mismatch: serialized={len(serialized)} rebuilt={reconstructed_count}")
    route_id = f"{target_id}__route_{route_index:03d}"
    candidates = []
    for item in serialized:
        precursor, product, reaction = canonicalize_reaction(item.precursors_raw, item.product_raw)
        candidates.append((item, precursor, product, reaction))
    candidates.sort(key=lambda x: (x[0].reaction_depth, x[2], x[1], x[0].original_serialized_index))
    rows = []
    route_is_solved = bool(route.get("metadata", {}).get("is_solved", rebuilt.is_solved))
    for step_index, (item, precursor, product, reaction) in enumerate(candidates, 1):
        rows.append({
            "target_id": str(target_id),
            "route_id": route_id,
            "step_id": f"{route_id}__step_{step_index:03d}",
            "route_index": int(route_index),
            "reaction_depth": int(item.reaction_depth),
            "original_serialized_index": int(item.original_serialized_index),
            "product_smiles_raw": item.product_raw,
            "precursor_smiles_raw": ".".join(item.precursors_raw),
            "reaction_smiles_raw": f"{'.'.join(item.precursors_raw)}>>{item.product_raw}",
            "product_smiles": product,
            "precursor_smiles": precursor,
            "reaction_smiles": reaction,
            "reaction_hash": reaction_hash(reaction),
            "original_reaction_metadata": json.dumps(item.metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "route_is_solved": route_is_solved,
            "original_route_rank": int(route_index),
        })
    return rows
