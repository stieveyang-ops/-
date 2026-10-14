"""Freeze development-only uncertainty quantiles in model metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="data/processed/reaction_features.parquet")
    ap.add_argument("--labels", default="data/labels/final_expert_labels.parquet")
    ap.add_argument("--train-ids", default="data/splits/train_ids.txt")
    ap.add_argument("--metadata", default="artifacts/difficulty_model_metadata.json")
    args = ap.parse_args()
    features_path, labels_path = (ROOT / args.features).resolve(), (ROOT / args.labels).resolve()
    train_path, metadata_path = (ROOT / args.train_ids).resolve(), (ROOT / args.metadata).resolve()
    report_path = ROOT / "reports/stage8_uncertainty_report.json"
    if report_path.exists():
        raise RuntimeError("uncertainty report already exists; refusing overwrite")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("train_ids_sha256") != digest(train_path):
        raise ValueError("train ID hash does not match model metadata")
    table = assign_leakage_groups(build_modeling_table(pd.read_parquet(features_path), pd.read_parquet(labels_path)))
    train_ids = {x.strip() for x in train_path.read_text(encoding="utf-8").splitlines() if x.strip()}
    dev = table[table.reaction_hash.isin(train_ids)].copy()
    if set(dev.reaction_hash) != train_ids:
        raise ValueError("train IDs do not match modeling table")
    u = compute_uncertainty(dev.p_feas.to_numpy(float), dev.p_prec.to_numpy(float))
    q33, q67 = fit_confidence_thresholds(u)
    confidence = assign_confidence(u, q33, q67)
    metadata.update({"uncertainty_formula": "[4*P_feas*(1-P_feas)+(1-P_prec)]/2", "quantile_method": "linear", "q33": q33, "q67": q67, "development_ids_sha256": digest(train_path), "source_feature_table_sha256": digest(features_path), "uncertainty_thresholds_pending": False})
    tmp = metadata_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(metadata_path)
    report = {"stage": 8, "status": "PASS", "development_n": len(dev), "u_dev_min": float(u.min()), "u_dev_max": float(u.max()), "u_dev_mean": float(u.mean()), "u_dev_median": float(np.median(u)), "q33": q33, "q67": q67, "quantile_method": "linear", "confidence_counts": {str(k): int(v) for k, v in pd.Series(confidence).value_counts().to_dict().items()}, "source": "development only", "locked_test_used": False, "formula": "[4*P_feas*(1-P_feas)+(1-P_prec)]/2"}
    tmpj = report_path.with_suffix(".json.tmp")
    tmpj.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    tmpj.replace(report_path)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
