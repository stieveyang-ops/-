"""Development-only CV diagnostics and final Stage 8 OrderedModel fit."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from aiz_rd.difficulty_model import ReactionDifficultyModel
from aiz_rd.splitting import assign_leakage_groups, build_modeling_table

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ["d_feas", "d_prec", "d_sc"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def read_ids(path: Path) -> list[str]:
    vals = [x.strip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(vals) != len(set(vals)):
        raise ValueError(f"duplicate IDs in {path}")
    return vals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="data/processed/reaction_features.parquet")
    ap.add_argument("--labels", default="data/labels/final_expert_labels.parquet")
    ap.add_argument("--train-ids", default="data/splits/train_ids.txt")
    ap.add_argument("--locked-test-ids", default="data/splits/test_ids_locked.txt")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force-version", action="store_true")
    args = ap.parse_args()
    features_path, labels_path = (ROOT / args.features).resolve(), (ROOT / args.labels).resolve()
    train_path, test_path = (ROOT / args.train_ids).resolve(), (ROOT / args.locked_test_ids).resolve()
    artifact = ROOT / "artifacts/difficulty_model.pkl"
    metadata_path = ROOT / "artifacts/difficulty_model_metadata.json"
    diag_path = ROOT / "reports/stage8_training_diagnostics.json"
    if not args.force_version and any(p.exists() for p in [artifact, metadata_path, diag_path]):
        raise RuntimeError("Stage 8 training output already exists; refusing overwrite")
    train_ids, test_ids = read_ids(train_path), read_ids(test_path)
    if set(train_ids) & set(test_ids):
        raise ValueError("locked test IDs overlap development IDs")
    table = assign_leakage_groups(build_modeling_table(pd.read_parquet(features_path), pd.read_parquet(labels_path)))
    labeled_ids = set(table.loc[table.final_status == "LABELED", "reaction_hash"])
    if set(train_ids) | set(test_ids) != labeled_ids:
        raise ValueError("split IDs do not cover exactly the labeled reaction-level modeling table")
    dev = table[table.reaction_hash.isin(train_ids)].copy()
    locked = table[table.reaction_hash.isin(test_ids)].copy()
    if set(dev.leakage_group_id) & set(locked.leakage_group_id):
        raise ValueError("leakage group overlaps locked test")
    if set(dev.expert_label.astype(int)) != {0, 1, 2}:
        raise ValueError("development set lacks one or more ordered classes")
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=args.seed)
    fold_diagnostics = []
    for fold, (tr_idx, val_idx) in enumerate(cv.split(dev, dev.expert_label.astype(int), dev.leakage_group_id)):
        xtr = dev.iloc[tr_idx][FEATURES]
        ytr = dev.iloc[tr_idx].expert_label.astype(int)
        if set(ytr) != {0, 1, 2}:
            raise RuntimeError(f"CV fold {fold} training data lacks a class")
        model = ReactionDifficultyModel().fit(xtr, ytr)
        params = model.metadata_parameters()
        fold_diagnostics.append({"fold": fold, "train_n": len(tr_idx), "validation_n": len(val_idx), "train_class_counts": {str(k): int(v) for k, v in ytr.value_counts().sort_index().items()}, "validation_class_counts": {str(k): int(v) for k, v in dev.iloc[val_idx].expert_label.value_counts().sort_index().items()}, "converged": model.converged, "coefficients_and_thresholds": params, "finite_parameters": bool(np.isfinite(list(params.values())).all())})
    final_model = ReactionDifficultyModel().fit(dev[FEATURES], dev.expert_label.astype(int))
    probabilities = final_model.predict_proba(dev[FEATURES])
    difficulty = final_model.predict_difficulty(dev[FEATURES])
    if not np.isfinite(probabilities).all() or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-10, rtol=0):
        raise RuntimeError("final development probabilities failed finite/sum checks")
    params = final_model.metadata_parameters()
    warnings = []
    for feature in FEATURES:
        if params.get(feature, 0.0) < 0:
            warnings.append({"type": "SCIENTIFIC_WARNING", "feature": feature, "message": "coefficient is negative; no manual correction applied"})
    metadata = {
        "model_name": "Ordinal Logistic Regression / OrderedModel",
        "distribution": "logit",
        "feature_order": FEATURES,
        "label_order": {"0": "Easy", "1": "Medium", "2": "Difficult"},
        "coefficients": {k: v for k, v in params.items() if k in FEATURES},
        "thresholds": {k: v for k, v in params.items() if k not in FEATURES},
        "all_parameters": params,
        "optimizer": "bfgs + maxiter=1000",
        "converged": bool(final_model.converged),
        "development_count": len(dev),
        "locked_test_count": len(locked),
        "train_ids_sha256": digest(train_path),
        "test_ids_sha256": digest(test_path),
        "input_feature_table_sha256": digest(features_path),
        "expert_label_file_sha256": digest(labels_path),
        "python_version": sys.version,
        "statsmodels_version": __import__("statsmodels").__version__,
        "sklearn_version": __import__("sklearn").__version__,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "random_seed": args.seed,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fit_on": "development only",
        "locked_test_used_for_fit": False,
        "locked_test_used_for_thresholds": False,
        "locked_test_used_for_hyperparameters": False,
        "feature_selection": "none; fixed [d_feas, d_prec, d_sc]",
        "uncertainty_thresholds_pending": True,
    }
    artifact.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact.with_suffix(".pkl.tmp")
    import pickle
    with tmp.open("wb") as fh:
        pickle.dump(final_model, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(artifact)
    metadata["model_artifact_sha256"] = digest(artifact)
    mtmp = metadata_path.with_suffix(".json.tmp")
    mtmp.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    mtmp.replace(metadata_path)
    diagnostics = {
        "stage": 8,
        "status": "PASS",
        "development_n": len(dev),
        "locked_test_n": len(locked),
        "class_counts": {str(k): int(v) for k, v in dev.expert_label.value_counts().sort_index().items()},
        "abstain_excluded_n": int((table.final_status == "ABSTAIN").sum()),
        "cv_folds": fold_diagnostics,
        "final_fit": {"fit_on": "development only", "converged": final_model.converged, "coefficients": metadata["coefficients"], "thresholds": metadata["thresholds"], "finite_probability_check": True, "probability_sum_to_one_check": True, "d_reaction_min": float(difficulty.min()), "d_reaction_median": float(np.median(difficulty)), "d_reaction_max": float(difficulty.max()), "scientific_warnings": warnings},
        "locked_test_used": False,
    }
    tmpd = diag_path.with_suffix(".json.tmp")
    tmpd.write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8")
    tmpd.replace(diag_path)
    print(json.dumps(diagnostics, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
