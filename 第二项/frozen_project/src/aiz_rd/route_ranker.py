"""Frozen-route aggregation and deterministic Stage 9 ranking."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from aizynthfinder.reactiontree import ReactionTree

from .chemistry import canonicalize_molecule_smiles
from .route_extractor import count_serialized_reactions

from dataclasses import dataclass


ROUTE_COLUMNS = [
    "target_id", "route_id", "original_rank", "new_rank", "solved",
    "rank_change",
    "original_state_score", "number_of_reactions", "difficulty_applicable",
    "difficulty_bottleneck", "difficulty_mean", "route_uncertainty",
    "route_confidence", "hardest_step_id", "hardest_step_ids",
    "hardest_step_reaction", "hardest_step_reactions", "route_hash", "route_hash_key", "route_type",
]


class RouteRankingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RouteDifficultyResult:
    number_of_reactions: int
    difficulty_applicable: bool
    difficulty_bottleneck: float | None
    difficulty_mean: float | None
    route_uncertainty: float | None
    route_confidence: str
    hardest_step_id: str | None
    hardest_step_ids: list[str]
    hardest_step_reaction: str | None
    hardest_step_reactions: list[str]
    route_type: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class RouteDifficultyEvaluator:
    """The single implementation of Stage 9 route aggregation formulas."""

    def __init__(self, q33: float, q67: float, feature_provider=None, model=None):
        if not (0 <= float(q33) <= float(q67) <= 1):
            raise RouteRankingError("invalid frozen confidence thresholds")
        self.q33, self.q67 = float(q33), float(q67)
        self.feature_provider = feature_provider
        self.model = model

    def score_route_steps(self, steps: pd.DataFrame) -> RouteDifficultyResult:
        values = _score_record(steps, self.q33, self.q67)
        return RouteDifficultyResult(**values)

    def score_reaction_tree(self, tree: ReactionTree, scored_steps: pd.DataFrame | None = None) -> RouteDifficultyResult:
        """Aggregate frozen scored occurrences, or derive them on demand."""
        if scored_steps is None:
            if self.feature_provider is None or self.model is None:
                raise RouteRankingError("tree scoring requires a feature provider and frozen model")
            rows = []
            from .chemistry import canonicalize_reaction, reaction_hash
            for reaction in tree.reactions():
                product = str(reaction.mol.smiles)
                precursor_nodes = [str(node.smiles) for node in tree.graph.successors(reaction)]
                precursor, _, canonical = canonicalize_reaction(precursor_nodes, product)
                key = reaction_hash(canonical)
                feature = self.feature_provider.score_components(product, precursor_nodes, expected_hash=key)
                if self.model is None:
                    raise RouteRankingError("on-demand tree scoring requires frozen ordinal model")
                probabilities = self.model.predict_proba(pd.DataFrame([[feature["d_feas"], feature["d_prec"], feature["d_sc"]]], columns=["d_feas", "d_prec", "d_sc"]))[0]
                rows.append({"step_id": key, "reaction_smiles": canonical, "reaction_difficulty": float(50 * probabilities[1] + 100 * probabilities[2]), "uncertainty": float((4 * feature["p_feas"] * (1 - feature["p_feas"]) + (1 - feature["p_prec"])) / 2)})
            scored_steps = pd.DataFrame(rows)
        expected = len(list(tree.reactions()))
        if len(scored_steps) != expected:
            raise RouteRankingError(f"tree/step score count mismatch: {expected} != {len(scored_steps)}")
        return self.score_route_steps(scored_steps)


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _target_mapping(targets_path: Path) -> dict[str, str]:
    targets = pd.read_csv(targets_path)
    if not {"target_id", "target_smiles"}.issubset(targets.columns):
        raise RouteRankingError("targets.csv schema mismatch")
    result = {}
    for row in targets.itertuples(index=False):
        key = canonicalize_molecule_smiles(str(row.target_smiles), "target")
        if key in result and result[key] != str(row.target_id):
            raise RouteRankingError("ambiguous target mapping")
        result[key] = str(row.target_id)
    return result


def _score_record(group: pd.DataFrame, q33: float, q67: float) -> dict[str, Any]:
    group = group.reset_index(drop=True)
    n = len(group)
    if n == 0:
        return {
            "number_of_reactions": 0, "difficulty_applicable": False,
            "difficulty_bottleneck": None, "difficulty_mean": None,
            "route_uncertainty": None, "route_confidence": "not_applicable",
            "hardest_step_id": None, "hardest_step_ids": [],
            "hardest_step_reaction": None, "hardest_step_reactions": [],
            "route_type": "direct_stock_no_reaction",
        }
    if group[["reaction_difficulty", "uncertainty"]].isna().any().any():
        raise RouteRankingError("route contains missing reaction score")
    d = group["reaction_difficulty"].to_numpy(dtype=float)
    u = group["uncertainty"].to_numpy(dtype=float)
    if not np.isfinite(d).all() or not np.isfinite(u).all():
        raise RouteRankingError("route contains non-finite reaction score")
    bottleneck = float(np.max(d))
    mean = float(np.mean(d))
    uncertainty = float(np.max(u))
    ties = np.flatnonzero(np.isclose(d, bottleneck, atol=1e-10, rtol=0.0)).tolist()
    step_ids = [str(group.iloc[i].step_id) for i in ties]
    reactions = [str(group.iloc[i].reaction_smiles) for i in ties]
    confidence = "high" if uncertainty <= q33 else ("medium" if uncertainty <= q67 else "low")
    return {
        "number_of_reactions": n, "difficulty_applicable": True,
        "difficulty_bottleneck": bottleneck, "difficulty_mean": mean,
        "route_uncertainty": uncertainty, "route_confidence": confidence,
        "hardest_step_id": step_ids[0], "hardest_step_ids": step_ids,
        "hardest_step_reaction": reactions[0], "hardest_step_reactions": reactions,
        "route_type": "reaction_route",
    }


def rank_routes(routes_path: Path, steps_path: Path, scored_path: Path, targets_path: Path,
                output_parquet: Path, output_csv: Path, output_json: Path,
                preview_path: Path, q33: float, q67: float) -> dict[str, Any]:
    raw = json.loads(routes_path.read_text(encoding="utf-8"))
    data = raw.get("data")
    if not isinstance(data, list):
        raise RouteRankingError("routes_raw.json is not pandas orient-table data")
    mapping = _target_mapping(targets_path)
    steps = pd.read_parquet(steps_path)
    scored = pd.read_parquet(scored_path)
    if "reaction_difficulty" not in scored.columns:
        raise RouteRankingError("scored reaction table lacks final scores")
    expected_route_ids = set(steps["route_id"].astype(str))
    records: list[dict[str, Any]] = []
    full_json: list[dict[str, Any]] = []
    for item in data:
        target_key = canonicalize_molecule_smiles(str(item["target"]), "routes target")
        if target_key not in mapping:
            raise RouteRankingError(f"route target cannot map: {item['target']}")
        target_id = mapping[target_key]
        for original_rank, tree_dict in enumerate(item.get("trees", []), 1):
            route_id = f"{target_id}__route_{original_rank:03d}"
            tree = ReactionTree.from_dict(tree_dict)
            serialized_count = count_serialized_reactions(tree_dict)
            if serialized_count != len(list(tree.reactions())):
                raise RouteRankingError(f"topology mismatch: {route_id}")
            route_steps = scored[scored.route_id.astype(str) == route_id].copy()
            frozen_steps = steps[steps.route_id.astype(str) == route_id].copy()
            if len(route_steps) != serialized_count:
                raise RouteRankingError(f"route-step coverage mismatch: {route_id}")
            if len(frozen_steps) != serialized_count:
                raise RouteRankingError(f"frozen route-step count mismatch: {route_id}")
            frozen_keys = frozen_steps[["target_id", "route_id", "step_id", "reaction_hash"]].astype(str).sort_values(["step_id"]).reset_index(drop=True)
            scored_keys = route_steps[["target_id", "route_id", "step_id", "reaction_hash"]].astype(str).sort_values(["step_id"]).reset_index(drop=True)
            if not frozen_keys.equals(scored_keys):
                raise RouteRankingError(f"route-step key/hash mismatch: {route_id}")
            if serialized_count and route_steps.step_id.duplicated().any():
                raise RouteRankingError(f"duplicate step id: {route_id}")
            solved_tree = bool(tree.is_solved)
            solved_metadata = tree_dict.get("metadata", {}).get("is_solved")
            if solved_metadata is not None and bool(solved_metadata) != solved_tree:
                raise RouteRankingError(f"solved state mismatch: {route_id}")
            score_obj = tree_dict.get("scores", {})
            state_score = score_obj.get("state score")
            if not isinstance(state_score, (int, float)) or not np.isfinite(float(state_score)):
                raise RouteRankingError(f"missing original state score: {route_id}")
            agg = _score_record(route_steps, q33, q67)
            rec = {"target_id": target_id, "route_id": route_id, "original_rank": original_rank,
                   "new_rank": None, "solved": solved_tree, "original_state_score": float(state_score),
                   **agg, "route_hash": _json_hash(tree_dict), "route_hash_key": _json_hash(tree_dict)}
            records.append(rec)
            full_json.append({**rec, "original_tree": tree_dict,
                              "steps": route_steps.to_dict(orient="records")})
    if set(r["route_id"] for r in records) != expected_route_ids:
        raise RouteRankingError("route universe mismatch")
    evaluator = RouteDifficultyEvaluator(q33, q67)
    # Re-run aggregation through the shared evaluator before ranking/output.
    for rec in records:
        route_steps = scored[scored.route_id.astype(str) == str(rec["route_id"])]
        rec.update(evaluator.score_route_steps(route_steps).as_dict())

    def key(r: dict[str, Any]):
        applicable = bool(r["difficulty_applicable"])
        return (-int(bool(r["solved"])), 0 if applicable else 1,
                r["difficulty_bottleneck"] if applicable else 0.0,
                r["difficulty_mean"] if applicable else 0.0,
                -float(r["original_state_score"]), int(r["original_rank"]), str(r["route_id"]))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        grouped.setdefault(str(rec["target_id"]), []).append(rec)
    for target_id, items in grouped.items():
        for rank, rec in enumerate(sorted(items, key=key), 1):
            rec["new_rank"] = rank
            rec["rank_change"] = int(rec["original_rank"]) - rank
    # Reflect the finalized rank fields in the JSON records.
    rank_by_route = {str(r["route_id"]): int(r["new_rank"]) for r in records}
    change_by_route = {str(r["route_id"]): int(r["rank_change"]) for r in records}
    for row in full_json:
        row["new_rank"] = rank_by_route[str(row["route_id"])]
        row["rank_change"] = change_by_route[str(row["route_id"])]
    records.sort(key=lambda r: (str(r["target_id"]), int(r["new_rank"])))
    out = pd.DataFrame(records, columns=ROUTE_COLUMNS)
    if out.new_rank.isna().any() or out.groupby("target_id").new_rank.apply(lambda x: x.tolist() != list(range(1, len(x) + 1))).any():
        raise RouteRankingError("new ranks are not contiguous")
    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_parquet.with_suffix(output_parquet.suffix + ".tmp"); out.to_parquet(tmp, index=False); tmp.replace(output_parquet)
    csv = out.copy()
    for col in ["hardest_step_ids", "hardest_step_reactions"]:
        csv[col] = csv[col].map(lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":")))
    tmp = output_csv.with_suffix(output_csv.suffix + ".tmp"); csv.to_csv(tmp, index=False); tmp.replace(output_csv)
    by_target = {}
    for row in full_json:
        row["new_rank"] = rank_by_route[str(row["route_id"])]
        by_target.setdefault(str(row["target_id"]), []).append(row)
    for target_id in by_target:
        by_target[target_id].sort(key=lambda x: int(x["new_rank"]))
    tmp = output_json.with_suffix(output_json.suffix + ".tmp"); tmp.write_text(json.dumps({"targets": by_target}, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(output_json)
    preview_rows = []
    for target_id, items in grouped.items():
        chosen = sorted(items, key=lambda r: int(r["original_rank"]))[:5] + sorted(items, key=lambda r: int(r["new_rank"]))[:5]
        seen = set()
        for r in chosen:
            if r["route_id"] in seen: continue
            seen.add(r["route_id"])
            preview_rows.append({k: r[k] for k in ["target_id", "route_id", "solved", "original_rank", "new_rank", "original_state_score", "difficulty_bottleneck", "difficulty_mean", "route_uncertainty", "route_confidence", "hardest_step_id", "hardest_step_reaction"]})
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_tmp = preview_path.with_suffix(preview_path.suffix + ".tmp")
    pd.DataFrame(preview_rows).to_csv(preview_tmp, index=False)
    preview_tmp.replace(preview_path)
    return {"targets": len(grouped), "routes": len(out), "solved_routes": int(out.solved.sum()),
            "unsolved_routes": int((~out.solved).sum()), "zero_reaction_routes": int((out.number_of_reactions == 0).sum()),
            "routes_with_changed_rank": int((out.original_rank != out.new_rank).sum())}
