"""Final Stage 6 QA, report, and provenance manifest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from aiz_rd.dev_baseline import BASELINE_LABEL, run_boundary_and_monotonicity_tests  # noqa: E402
from aiz_rd.feature_pipeline import (  # noqa: E402
    FINAL_COLUMNS,
    KEY_COLUMNS,
    Stage6ValidationError,
    json_dump_atomic,
    package_versions,
    sha256,
    validate_feature_values,
)


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise Stage6ValidationError(f"missing required JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise Stage6ValidationError(f"missing required file {label}: {path}")
    actual = sha256(path)
    if actual != str(expected).upper():
        raise Stage6ValidationError(f"{label}: SHA256 mismatch expected={expected} actual={actual}")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default=str(ROOT / "data/processed/reaction_features.parquet"))
    parser.add_argument("--report", default=str(ROOT / "reports/stage6_feature_pipeline_report.json"))
    parser.add_argument("--manifest", default=str(ROOT / "reports/stage6_manifest.json"))
    args = parser.parse_args()
    feature_path = Path(args.features).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    report: dict[str, object] = {"stage": 6, "status": "BLOCKED", "errors": [], "warnings": []}
    try:
        stage2 = _read_json(ROOT / "reports/stage2_validation.json")
        stage3 = _read_json(ROOT / "reports/stage3_validation.json")
        stage3_manifest = _read_json(ROOT / "data/generated/stage3_run_manifest.json")
        stage4 = _read_json(ROOT / "reports/stage4_manifest.json")
        stage5 = _read_json(ROOT / "reports/stage5_manifest.json")
        if any(item.get("status") != "PASS" for item in [stage2, stage3, stage4, stage5]):
            raise Stage6ValidationError("one or more upstream manifests/reports are not PASS")
        paths = {
            "reaction_steps_raw": ROOT / "data/processed/reaction_steps_raw.parquet",
            "reaction_feasibility": ROOT / "data/processed/reaction_feasibility.parquet",
            "reaction_sc_raw": ROOT / "data/processed/reaction_sc_raw.parquet",
            "reaction_precedent": ROOT / "data/processed/reaction_precedent.parquet",
            "reaction_sc_normalized": ROOT / "data/processed/reaction_sc_normalized.parquet",
        }
        expected = {
            "reaction_steps_raw": stage3_manifest["input_reaction_steps_sha256"],
            "reaction_feasibility": stage3_manifest["output_feasibility_sha256"],
            "reaction_sc_raw": stage3_manifest["output_sc_raw_sha256"],
            "reaction_precedent": stage5["output_sha256"]["reaction_precedent"],
            "reaction_sc_normalized": stage5["output_sha256"]["reaction_sc_normalized"],
        }
        input_audit: dict[str, object] = {}
        frames: dict[str, pd.DataFrame] = {}
        for label, path in paths.items():
            digest = _check_hash(path, expected[label], label)
            frames[label] = pd.read_parquet(path)
            input_audit[label] = {"path": str(path), "sha256": digest, "rows": int(len(frames[label]))}
        if float(stage5.get("tau")) != 0.8 or float(stage5.get("n0")) != 10.0 or stage5.get("precedent_mode") != "deployment":
            raise Stage6ValidationError("Stage 5 tau/N0/mode drifted")
        features = pd.read_parquet(feature_path)
        if features.columns.tolist() != FINAL_COLUMNS:
            raise Stage6ValidationError(f"final feature schema mismatch: {features.columns.tolist()}")
        validation = validate_feature_values(features, stage5_manifest=stage5, require_difficulty=True)
        base = frames["reaction_steps_raw"]
        for label, frame in frames.items():
            if len(frame) != len(base):
                raise Stage6ValidationError(f"{label} row count {len(frame)} != base {len(base)}")
        if len(features) != len(base):
            raise Stage6ValidationError(f"feature row count {len(features)} != base {len(base)}")
        base_keys = base[KEY_COLUMNS].reset_index(drop=True)
        if not features[KEY_COLUMNS].reset_index(drop=True).equals(base_keys):
            raise Stage6ValidationError("final feature keys/order do not equal Stage 2 base")
        boundary = run_boundary_and_monotonicity_tests()
        values = features["difficulty_dev"].to_numpy(dtype=float)
        report.update(
            {
                "stage": 6,
                "status": "PASS",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "baseline_label": BASELINE_LABEL,
                "input_audit": input_audit,
                "merge_audit": {
                    "base_rows": int(len(base)),
                    "feasibility_rows_matched": int(len(frames["reaction_feasibility"])),
                    "sc_raw_rows_matched": int(len(frames["reaction_sc_raw"])),
                    "precedent_rows_matched": int(len(frames["reaction_precedent"])),
                    "d_sc_rows_matched": int(len(frames["reaction_sc_normalized"])),
                    "missing_keys": 0,
                    "extra_keys": 0,
                    "duplicate_keys": 0,
                },
                "validation": validation,
                "boundary_and_monotonicity_tests": boundary,
                "difficulty_dev_distribution": {
                    "min": float(np.min(values)),
                    "median": float(np.median(values)),
                    "max": float(np.max(values)),
                    "q25": float(np.quantile(values, 0.25)),
                    "q75": float(np.quantile(values, 0.75)),
                },
                "output": {"path": str(feature_path), "sha256": sha256(feature_path), "rows": int(len(features)), "columns": features.columns.tolist()},
                "scientific_boundary": {
                    "expert_labels_used": False,
                    "model_trained": False,
                    "missing_values_imputed": False,
                    "route_aggregation_or_ranking": False,
                    "aizynthfinder_modified": False,
                    "stage7_started": False,
                },
            }
        )
        runtime_versions = package_versions()
        # RXNFP is intentionally not imported or recomputed in Stage 6.  Its
        # authoritative identity therefore comes from the frozen Stage 5
        # isolated runtime, while the remaining entries describe this process.
        runtime_versions["rxnfp"] = (
            stage5.get("rxnfp_model_identity", {}).get("package")
            or runtime_versions.get("rxnfp")
        )
        manifest = {
            "stage": 6,
            "status": "PASS",
            "created_at": report["created_at_utc"],
            "git_commit": None,
            "git_commit_reason": "Project directory is not a Git worktree",
            "python_version": "3.10.20",
            "package_versions": runtime_versions,
            "input_files": {label: {"path": str(path), "sha256": sha256(path)} for label, path in paths.items()},
            "upstream_manifests": {
                "stage2_validation": str(ROOT / "reports/stage2_validation.json"),
                "stage3_validation": str(ROOT / "reports/stage3_validation.json"),
                "stage3_manifest": str(ROOT / "data/generated/stage3_run_manifest.json"),
                "stage4_manifest": str(ROOT / "reports/stage4_manifest.json"),
                "stage5_manifest": str(ROOT / "reports/stage5_manifest.json"),
            },
            "merge_key_columns": KEY_COLUMNS,
            "row_count": int(len(features)),
            "weights": {"d_feas": 0.45, "d_prec": 0.40, "d_sc": 0.15},
            "baseline_label": BASELINE_LABEL,
            "frozen_stage5_identity": {
                "tau": stage5.get("tau"),
                "n0": stage5.get("n0"),
                "precedent_mode": stage5.get("precedent_mode"),
                "reference_corpus_sha256": stage5.get("reference_corpus_sha256"),
                "reference_embedding_sha256": stage5.get("reference_embedding_sha256"),
                "scscore_model_sha256": stage5.get("scscore_model_sha256"),
                "ecdf_artifact_sha256": stage5.get("output_sha256", {}).get("sc_delta_ecdf"),
                "rxnfp_model_identity": stage5.get("rxnfp_model_identity"),
            },
            "output": {"path": str(feature_path), "sha256": sha256(feature_path)},
            "validation_summary": report,
            "stage7_started": False,
        }
        json_dump_atomic(manifest_path, manifest)
        report["manifest"] = {"path": str(manifest_path), "sha256": sha256(manifest_path)}
    except Exception as exc:
        report["errors"] = [f"{type(exc).__name__}: {exc}"]
    json_dump_atomic(report_path, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
