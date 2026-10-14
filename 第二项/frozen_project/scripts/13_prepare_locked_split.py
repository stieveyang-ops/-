"""Create the immutable Stage 8 development/locked-test split."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from aiz_rd.splitting import assign_leakage_groups, build_modeling_table, locked_split

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="data/processed/reaction_features.parquet")
    ap.add_argument("--labels", default="data/labels/final_expert_labels.parquet")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force-version", action="store_true")
    args = ap.parse_args()
    features_path = (ROOT / args.features).resolve()
    labels_path = (ROOT / args.labels).resolve()
    split_dir = ROOT / "data/splits"
    outputs = [split_dir / "train_ids.txt", split_dir / "test_ids_locked.txt", split_dir / "split_assignments.parquet", ROOT / "reports/stage8_split_report.json"]
    if not args.force_version and any(p.exists() for p in outputs):
        raise RuntimeError("Stage 8 split output already exists; refusing overwrite")
    features = pd.read_parquet(features_path)
    labels = pd.read_parquet(labels_path)
    table = assign_leakage_groups(build_modeling_table(features, labels))
    development, locked_test, strategy, folds = locked_split(table, seed=args.seed)
    train_ids = development.reaction_hash.astype(str).tolist()
    test_ids = locked_test.reaction_hash.astype(str).tolist()
    atomic_text(split_dir / "train_ids.txt", "".join(x + "\n" for x in train_ids))
    atomic_text(split_dir / "test_ids_locked.txt", "".join(x + "\n" for x in test_ids))
    assignments = table[["reaction_hash", "leakage_group_id", "target_ids", "expert_label", "final_status"]].copy()
    assignments["split"] = assignments.apply(lambda row: "development" if row.reaction_hash in set(train_ids) else ("locked_test" if row.reaction_hash in set(test_ids) else "excluded_abstain"), axis=1)
    assignments["target_ids"] = assignments.target_ids.map(lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":")))
    tmp = split_dir / "split_assignments.parquet.tmp"
    split_dir.mkdir(parents=True, exist_ok=True)
    assignments.to_parquet(tmp, index=False)
    pd.read_parquet(tmp)
    tmp.replace(split_dir / "split_assignments.parquet")
    dev_targets = set(t for values in development.target_ids for t in values)
    test_targets = set(t for values in locked_test.target_ids for t in values)
    report = {
        "stage": 8,
        "status": "PASS",
        "split_strategy": strategy,
        "random_state": args.seed,
        "target_test_fraction": 0.20,
        "actual_test_fraction": len(locked_test) / len(table[table.final_status == "LABELED"]),
        "development_reactions": len(development),
        "locked_test_reactions": len(locked_test),
        "development_leakage_groups": int(development.leakage_group_id.nunique()),
        "locked_test_leakage_groups": int(locked_test.leakage_group_id.nunique()),
        "development_class_counts": {str(k): int(v) for k, v in development.expert_label.value_counts().sort_index().items()},
        "locked_test_class_counts": {str(k): int(v) for k, v in locked_test.expert_label.value_counts().sort_index().items()},
        "reaction_hash_overlap": len(set(train_ids) & set(test_ids)),
        "target_id_overlap": len(dev_targets & test_targets),
        "leakage_group_overlap": len(set(development.leakage_group_id) & set(locked_test.leakage_group_id)),
        "train_ids_sha256": digest(split_dir / "train_ids.txt"),
        "test_ids_sha256": digest(split_dir / "test_ids_locked.txt"),
        "modeling_reaction_hashes": int(len(table[table.final_status == "LABELED"])),
        "abstain_excluded": int((table.final_status == "ABSTAIN").sum()),
        "cv_fold_sizes": [{"fold": i, "train": len(tr), "test": len(te)} for i, (tr, te) in enumerate(folds)],
    }
    out = ROOT / "reports/stage8_split_report.json"
    tmpj = out.with_suffix(".json.tmp")
    tmpj.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    tmpj.replace(out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
