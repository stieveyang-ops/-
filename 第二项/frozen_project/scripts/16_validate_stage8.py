"""Final Stage 8 integrity audit; does not evaluate locked-test performance."""
from __future__ import annotations

import hashlib
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from aiz_rd.difficulty_model import ReactionDifficultyModel
from aiz_rd.splitting import assign_leakage_groups, build_modeling_table
from aiz_rd.uncertainty import compute_uncertainty, fit_confidence_thresholds, assign_confidence

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def main() -> int:
    errors = []
    feat_path = ROOT / "data/processed/reaction_features.parquet"
    labels_path = ROOT / "data/labels/final_expert_labels.parquet"
    train_path = ROOT / "data/splits/train_ids.txt"
    test_path = ROOT / "data/splits/test_ids_locked.txt"
    assign_path = ROOT / "data/splits/split_assignments.parquet"
    artifact = ROOT / "artifacts/difficulty_model.pkl"
    metadata_path = ROOT / "artifacts/difficulty_model_metadata.json"
    split_report_path = ROOT / "reports/stage8_split_report.json"
    diag_path = ROOT / "reports/stage8_training_diagnostics.json"
    unc_path = ROOT / "reports/stage8_uncertainty_report.json"
    required = [feat_path, labels_path, train_path, test_path, assign_path, artifact, metadata_path, split_report_path, diag_path, unc_path]
    if not all(p.exists() for p in required):
        missing = [str(p) for p in required if not p.exists()]
        raise RuntimeError(f"missing Stage 8 outputs: {missing}")
    features = pd.read_parquet(feat_path); labels = pd.read_parquet(labels_path)
    table = assign_leakage_groups(build_modeling_table(features, labels))
    train_ids = {x.strip() for x in train_path.read_text(encoding="utf-8").splitlines() if x.strip()}; test_ids = {x.strip() for x in test_path.read_text(encoding="utf-8").splitlines() if x.strip()}
    dev, test = table[table.reaction_hash.isin(train_ids)], table[table.reaction_hash.isin(test_ids)]
    if train_ids & test_ids: errors.append("train/test ID overlap")
    if set(dev.leakage_group_id) & set(test.leakage_group_id): errors.append("leakage group overlap")
    if set(t for x in dev.target_ids for t in x) & set(t for x in test.target_ids for t in x): errors.append("target overlap")
    if len(table) != table.reaction_hash.nunique(): errors.append("duplicate reaction-level modeling sample")
    if set(dev.reaction_hash) | set(test.reaction_hash) != set(table.loc[table.final_status == "LABELED", "reaction_hash"]): errors.append("split does not cover exactly labeled samples")
    if set(dev.expert_label.astype(int)) != {0,1,2}: errors.append("development class missing")
    if labels[labels.final_status == "ABSTAIN"].shape[0] != 9: errors.append("unexpected abstain count")
    metadata=json.loads(metadata_path.read_text(encoding="utf-8")); model=ReactionDifficultyModel.load(artifact,metadata_path)
    if metadata.get("feature_order") != ["d_feas","d_prec","d_sc"]: errors.append("feature order mismatch")
    if metadata.get("input_feature_table_sha256") != digest(feat_path): errors.append("feature hash mismatch")
    if metadata.get("expert_label_file_sha256") != digest(labels_path): errors.append("label hash mismatch")
    if metadata.get("train_ids_sha256") != digest(train_path): errors.append("train hash mismatch")
    if metadata.get("test_ids_sha256") != digest(test_path): errors.append("test hash mismatch")
    probs=model.predict_proba(dev[["d_feas","d_prec","d_sc"]]); diff=model.predict_difficulty(dev[["d_feas","d_prec","d_sc"]])
    if probs.shape[1] != 3 or not np.isfinite(probs).all() or not np.allclose(probs.sum(axis=1),1,atol=1e-10,rtol=0): errors.append("invalid model probabilities")
    if not np.isfinite(diff).all() or ((diff<0)|(diff>100)).any(): errors.append("invalid difficulty")
    if metadata.get("q33") is None or metadata.get("q67") is None or not (0 <= metadata["q33"] <= metadata["q67"] <= 1): errors.append("invalid uncertainty thresholds")
    u=compute_uncertainty(dev.p_feas.to_numpy(float),dev.p_prec.to_numpy(float)); q33,q67=fit_confidence_thresholds(u)
    if not (np.isclose(q33,metadata["q33"]) and np.isclose(q67,metadata["q67"])): errors.append("threshold source mismatch")
    if errors: raise RuntimeError("; ".join(errors))
    manifest={"stage":8,"status":"PASS","input_file_hashes":{"reaction_features":digest(feat_path),"final_expert_labels":digest(labels_path),"stage6_manifest":digest(ROOT/'reports/stage6_manifest.json'),"stage7_manifest":digest(ROOT/'reports/stage7_annotation_manifest.json')},"train_ids_sha256":digest(train_path),"test_ids_sha256":digest(test_path),"split_strategy":json.loads(split_report_path.read_text())["split_strategy"],"random_seed":42,"feature_order":["d_feas","d_prec","d_sc"],"model_artifact_sha256":digest(artifact),"model_metadata_sha256":digest(metadata_path),"q33":metadata["q33"],"q67":metadata["q67"],"package_versions":{"python":sys.version,"statsmodels":__import__("statsmodels").__version__,"numpy":np.__version__,"pandas":pd.__version__,"sklearn":__import__("sklearn").__version__},"created_at":datetime.now(timezone.utc).isoformat(),"all_tests_passed":True,"locked_test_used_for_fit":False,"locked_test_used_for_cv":False,"locked_test_used_for_thresholds":False,"stage9_started":False,"scientific_statement":"The final reaction-difficulty model is a condition-agnostic ordinal model trained exclusively on human expert labels using three predictors: feasibility difficulty (D_F), precedent difficulty (D_P), and normalized delta synthetic complexity (D_SC). The locked test set was not used for model fitting, feature selection, threshold selection, uncertainty calibration, or hyperparameter selection. Reaction difficulty is a relative expert-aligned score and must not be interpreted as experimental success probability or reaction yield."}
    out=ROOT/'reports/stage8_manifest.json'; tmp=out.with_suffix('.json.tmp'); tmp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8'); tmp.replace(out); print(json.dumps(manifest,indent=2,ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
