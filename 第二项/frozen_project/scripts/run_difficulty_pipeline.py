#!/usr/bin/env python
"""The single production-like Stage 11 inference entry point.

This command consumes frozen Stage 2--10 artifacts and never reads labels,
split files, benchmark predictions, or any training input.  It is deliberately
fail-fast: a missing/hash-mismatched artifact or non-finite value aborts the
run instead of silently repairing the scientific inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiz_rd.chemistry import canonicalize_molecule_smiles
from aiz_rd.explanations import reaction_explanation, route_explanation
from aiz_rd.provenance import canonical_content_hash, runtime_versions, sha256
from aiz_rd.reaction_inference import load_frozen_model, REACTION_OUTPUT_COLUMNS
from aiz_rd.route_extractor import extract_route_rows


class PipelineBlocked(RuntimeError):
    pass


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _native(value):
    """Convert NumPy/pandas scalar values to JSON-native Python values."""
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False)
    tmp.replace(path)


def _check_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise PipelineBlocked(f"missing frozen artifact: {label}: {path}")
    actual = sha256(path)
    if actual.upper() != str(expected).upper():
        raise PipelineBlocked(f"hash mismatch for {label}: {actual} != {expected}")


def _validate_config(config_path: Path) -> dict:
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PipelineBlocked(f"cannot read config: {exc}") from exc
    if not isinstance(config, dict) or config.get("schema_version") != "1.0" or config.get("mode") != "deployment":
        raise PipelineBlocked("difficulty.yml must declare schema_version=1.0 and mode=deployment")
    if config.get("feature_order") != ["d_feas", "d_prec", "d_sc"]:
        raise PipelineBlocked("feature order is not exactly [d_feas, d_prec, d_sc]")
    precedent = config.get("precedent", {})
    if float(precedent.get("tau", -1)) != 0.80 or float(precedent.get("N0", -1)) != 10.0:
        raise PipelineBlocked("primary precedent parameters are not tau=0.80, N0=10")
    return config


def _target_map() -> dict[str, str]:
    path = ROOT / "data/raw/targets.csv"
    frame = pd.read_csv(path)
    if not {"target_id", "target_smiles"}.issubset(frame.columns):
        raise PipelineBlocked("targets.csv schema mismatch")
    result: dict[str, str] = {}
    for row in frame.itertuples(index=False):
        key = canonicalize_molecule_smiles(str(row.target_smiles), "target")
        value = str(row.target_id)
        if key in result and result[key] != value:
            raise PipelineBlocked(f"ambiguous target mapping for {key}")
        result[key] = value
    return result


def _frozen_checks(reference_path: Path, config_path: Path) -> tuple[pd.DataFrame, object, dict, dict]:
    config = _validate_config(config_path)
    stage5 = json.loads((ROOT / "reports/stage5_manifest.json").read_text(encoding="utf-8"))
    reference_expected = stage5.get("reference_corpus_sha256")
    if not reference_expected:
        raise PipelineBlocked("stage5 manifest lacks reference corpus hash")
    _check_hash(reference_path, reference_expected, "reference corpus")
    stage8_path = ROOT / "reports/stage8_manifest.json"
    stage8 = json.loads(stage8_path.read_text(encoding="utf-8"))
    features_path = ROOT / "data/processed/reaction_features.parquet"
    expected_features = stage8.get("input_file_hashes", {}).get("reaction_features")
    if not expected_features:
        raise PipelineBlocked("stage8 manifest lacks reaction feature hash")
    _check_hash(features_path, expected_features, "reaction features")
    model_path = ROOT / "artifacts/difficulty_model.pkl"
    metadata_path = ROOT / "artifacts/difficulty_model_metadata.json"
    model, metadata, _ = load_frozen_model(model_path, metadata_path, stage8_path)
    frame = pd.read_parquet(features_path)
    required = {"reaction_hash", "p_feas", "p_prec", "d_feas", "d_prec", "d_sc"}
    if not required.issubset(frame.columns):
        raise PipelineBlocked("frozen reaction feature schema mismatch")
    values = frame[["p_feas", "p_prec", "d_feas", "d_prec", "d_sc"]].to_numpy(float)
    if not np.isfinite(values).all() or ((values[:, [0, 1, 2, 3, 4]] < 0) | (values[:, [0, 1, 2, 3, 4]] > 1)).any():
        raise PipelineBlocked("frozen feature table contains non-finite/out-of-range values")
    return frame, model, metadata, config


def _score_occurrences(routes_path: Path, features: pd.DataFrame, model, metadata: dict) -> tuple[pd.DataFrame, list[dict]]:
    raw = json.loads(routes_path.read_text(encoding="utf-8"))
    if not isinstance(raw.get("data"), list):
        raise PipelineBlocked("routes input must be pandas orient=table JSON")
    target_map = _target_map()
    frozen = features.drop_duplicates("reaction_hash", keep="first").set_index("reaction_hash")
    hashes = frozen.index.astype(str).tolist()
    X = frozen[["d_feas", "d_prec", "d_sc"]]
    probabilities = model.predict_proba(X)
    if probabilities.shape != (len(frozen), 3) or not np.isfinite(probabilities).all() or not np.allclose(probabilities.sum(1), 1.0, atol=1e-10):
        raise PipelineBlocked("frozen model produced invalid probabilities")
    score_by_hash: dict[str, dict] = {}
    q33, q67 = float(metadata["q33"]), float(metadata["q67"])
    for idx, key in enumerate(hashes):
        row = frozen.iloc[idx]
        p = probabilities[idx]
        difficulty = float(50.0 * p[1] + 100.0 * p[2])
        uncertainty = float((4.0 * row.p_feas * (1.0 - row.p_feas) + (1.0 - row.p_prec)) / 2.0)
        if not (0 <= difficulty <= 100 and 0 <= uncertainty <= 1):
            raise PipelineBlocked("model output outside frozen bounds")
        confidence = "High" if uncertainty <= q33 else ("Medium" if uncertainty <= q67 else "Low")
        values = {c: _native(row[c]) for c in REACTION_OUTPUT_COLUMNS if c in row.index}
        values.update({"p_easy": float(p[0]), "p_medium": float(p[1]), "p_difficult": float(p[2]), "reaction_difficulty": difficulty, "uncertainty": uncertainty, "confidence": confidence})
        code, text = reaction_explanation(values)
        values.update({"explanation_code": code, "explanation_text": text})
        score_by_hash[key] = values
    occurrences: list[dict] = []
    routes: list[dict] = []
    for item in raw["data"]:
        target_key = canonicalize_molecule_smiles(str(item.get("target", "")), "route target")
        if target_key not in target_map:
            raise PipelineBlocked(f"route target is absent from targets.csv: {item.get('target')}")
        target_id = target_map[target_key]
        for route_index, tree in enumerate(item.get("trees", []), 1):
            route_id = f"{target_id}__route_{route_index:03d}"
            extracted = extract_route_rows(target_id, route_index, tree)
            route_steps = []
            for extracted_row in extracted:
                key = str(extracted_row["reaction_hash"])
                if key not in score_by_hash:
                    raise PipelineBlocked(f"route reaction is absent from frozen feature table: {key}")
                row = dict(score_by_hash[key])
                row.update({"target_id": target_id, "route_id": route_id, "step_id": extracted_row["step_id"], "reaction_hash": key, "reaction_smiles": extracted_row["reaction_smiles"], "product_smiles": extracted_row["product_smiles"], "precursor_smiles": extracted_row["precursor_smiles"]})
                occurrences.append(row)
                route_steps.append(row)
            state_score = tree.get("scores", {}).get("state score", 0.0)
            if not isinstance(state_score, (int, float)) or not np.isfinite(float(state_score)):
                raise PipelineBlocked(f"missing state score: {route_id}")
            solved = bool(tree.get("metadata", {}).get("is_solved", False))
            if route_steps:
                d = np.array([float(x["reaction_difficulty"]) for x in route_steps])
                u = np.array([float(x["uncertainty"]) for x in route_steps])
                bottleneck = float(d.max()); mean = float(d.mean()); ru = float(u.max())
                ties = [i for i, value in enumerate(d) if np.isclose(value, bottleneck, atol=1e-10, rtol=0)]
                hardest_ids = [str(route_steps[i]["step_id"]) for i in ties]
                hardest_reactions = [str(route_steps[i]["reaction_smiles"]) for i in ties]
                confidence = "high" if ru <= q33 else ("medium" if ru <= q67 else "low")
                applicable = True
            else:
                bottleneck = mean = ru = None; hardest_ids = []; hardest_reactions = []; confidence = "not_applicable"; applicable = False
            route = {"target_id": target_id, "route_id": route_id, "original_rank": route_index, "solved": solved, "original_state_score": float(state_score), "number_of_reactions": len(route_steps), "difficulty_applicable": applicable, "difficulty_bottleneck": bottleneck, "difficulty_mean": mean, "route_uncertainty": ru, "route_confidence": confidence, "hardest_step_id": hardest_ids[0] if hardest_ids else None, "hardest_step_ids": hardest_ids, "hardest_step_reaction": hardest_reactions[0] if hardest_reactions else None, "hardest_step_reactions": hardest_reactions, "steps": route_steps}
            route["route_explanation"] = route_explanation(route)
            routes.append(route)
    # Apply the frozen Stage 9 lexicographic route ranking independently per target.
    grouped: dict[str, list[dict]] = {}
    for route in routes:
        grouped.setdefault(str(route["target_id"]), []).append(route)
    for target_id, group in grouped.items():
        def key(route: dict):
            applicable = bool(route["difficulty_applicable"])
            return (-int(bool(route["solved"])), 0 if applicable else 1, route["difficulty_bottleneck"] if applicable else 0.0, route["difficulty_mean"] if applicable else 0.0, -float(route["original_state_score"]), int(route["original_rank"]), str(route["route_id"]))
        for new_rank, route in enumerate(sorted(group, key=key), 1):
            route["new_rank"] = new_rank
            route["rank_change"] = int(route["original_rank"]) - new_rank
    out = pd.DataFrame(occurrences)
    if len(out) != len(features):
        raise PipelineBlocked(f"route/feature row count mismatch: {len(out)} != {len(features)}")
    # Stable schema and column order; all required scientific columns are retained.
    columns = REACTION_OUTPUT_COLUMNS + ["explanation_code", "explanation_text"]
    if any(c not in out for c in columns):
        raise PipelineBlocked("scored reaction output schema incomplete")
    out = out[columns]
    return out, routes


def run(routes_path: Path, reference_path: Path, config_path: Path, output_path: Path) -> dict:
    if not routes_path.is_file():
        raise PipelineBlocked(f"routes file missing: {routes_path}")
    features, model, metadata, config = _frozen_checks(reference_path, config_path)
    scored, routes = _score_occurrences(routes_path, features, model, metadata)
    output_path = output_path.resolve()
    reaction_output = output_path.parent / "scored_reactions.parquet"
    routes_output = output_path
    csv_output = output_path.with_suffix(".csv")
    _atomic_parquet(reaction_output, scored)
    route_json = {"targets": {}}
    for route in routes:
        clean = {k: v for k, v in route.items() if k != "steps"}
        clean["steps"] = route["steps"]
        route_json["targets"].setdefault(str(route["target_id"]), []).append(clean)
    for target_id in route_json["targets"]:
        route_json["targets"][target_id].sort(key=lambda x: int(x["new_rank"]))
    _atomic_json(routes_output, route_json)
    flat_routes = []
    for target_routes in route_json["targets"].values():
        for route in target_routes:
            flat_routes.append({k: v for k, v in route.items() if k != "steps"})
    route_csv = pd.DataFrame(flat_routes)
    if not route_csv.empty:
        for col in ["hardest_step_ids", "hardest_step_reactions"]:
            route_csv[col] = route_csv[col].map(lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":")))
    _atomic_csv(csv_output, route_csv)
    metadata_path = ROOT / "reports/run_metadata.json"
    run_metadata = {"schema_version": "1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(), "python_executable": sys.executable, "runtime_versions": runtime_versions(), "routes_path": str(routes_path.resolve()), "reference_path": str(reference_path.resolve()), "config_path": str(config_path.resolve()), "input_hashes": {"routes": sha256(routes_path), "reference": sha256(reference_path), "config": sha256(config_path), "reaction_features": sha256(ROOT / "data/processed/reaction_features.parquet"), "difficulty_model": sha256(ROOT / "artifacts/difficulty_model.pkl"), "difficulty_model_metadata": sha256(ROOT / "artifacts/difficulty_model_metadata.json")}, "output_hashes": {"scored_reactions": sha256(reaction_output), "scored_routes": sha256(routes_output), "scored_routes_csv": sha256(csv_output)}, "output_content_hashes": {"scored_routes": canonical_content_hash(routes_output)}, "feature_order": ["d_feas", "d_prec", "d_sc"], "precedent": {"tau": 0.80, "N0": 10.0, "mode": "deployment"}, "q33": float(metadata["q33"]), "q67": float(metadata["q67"]), "labels_or_locked_test_read": False, "training_or_refit": False, "stage12_started": False, "counts": {"reaction_rows": len(scored), "route_count": len(routes), "target_count": len(route_json["targets"])}}
    _atomic_json(metadata_path, run_metadata)
    return {"status": "PASS", "scored_reactions": str(reaction_output), "scored_routes": str(routes_output), "run_metadata": str(metadata_path), "reaction_rows": len(scored), "routes": len(routes), "targets": len(route_json["targets"]), "output_hashes": run_metadata["output_hashes"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen AiZynthFinder reaction-difficulty inference")
    parser.add_argument("--routes", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = run(Path(args.routes), Path(args.reference), Path(args.config), Path(args.output))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
