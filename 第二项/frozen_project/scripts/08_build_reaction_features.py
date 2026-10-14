"""Build the strict Stage 6 reaction feature table (without D_dev)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from aiz_rd.feature_pipeline import (  # noqa: E402
    FEATURE_COLUMNS,
    Stage6ValidationError,
    atomic_write_parquet,
    build_features,
    json_dump_atomic,
    package_versions,
    sha256,
)


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise Stage6ValidationError(f"missing provenance file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Stage6ValidationError(f"cannot read JSON provenance {path}: {exc}") from exc


def _require_pass(report: dict, path: Path) -> None:
    if report.get("status") != "PASS" or report.get("validation_status") == "FAIL":
        raise Stage6ValidationError(f"upstream report is not PASS: {path}")


def _expected_hashes() -> tuple[dict[str, str], dict[str, dict]]:
    stage2_validation_path = ROOT / "reports/stage2_validation.json"
    stage3_validation_path = ROOT / "reports/stage3_validation.json"
    stage3_manifest_path = ROOT / "data/generated/stage3_run_manifest.json"
    stage5_manifest_path = ROOT / "reports/stage5_manifest.json"
    stage4_manifest_path = ROOT / "reports/stage4_manifest.json"
    stage2 = _read_json(stage2_validation_path)
    stage3 = _read_json(stage3_validation_path)
    stage3_manifest = _read_json(stage3_manifest_path)
    stage4_manifest = _read_json(stage4_manifest_path)
    stage5 = _read_json(stage5_manifest_path)
    for report, path in [(stage2, stage2_validation_path), (stage3, stage3_validation_path), (stage4_manifest, stage4_manifest_path), (stage5, stage5_manifest_path)]:
        _require_pass(report, path)
    if stage3_manifest.get("stage") != 3 or stage3_manifest.get("reaction_row_count") != 828:
        raise Stage6ValidationError("Stage 3 manifest is missing or has incompatible row universe")
    if stage5.get("stage") != 5:
        raise Stage6ValidationError("Stage 5 manifest is missing or incompatible")
    hashes = {
        "reaction_steps_raw": str(stage3_manifest["input_reaction_steps_sha256"]).upper(),
        "reaction_feasibility": str(stage3_manifest["output_feasibility_sha256"]).upper(),
        "reaction_sc_raw": str(stage3_manifest["output_sc_raw_sha256"]).upper(),
        "reaction_precedent": str(stage5["output_sha256"]["reaction_precedent"]).upper(),
        "reaction_sc_normalized": str(stage5["output_sha256"]["reaction_sc_normalized"]).upper(),
    }
    if str(stage2.get("reaction_steps_raw_sha256", "")).upper() != hashes["reaction_steps_raw"]:
        raise Stage6ValidationError("Stage 2 and Stage 3 reaction_steps_raw provenance disagree")
    if str(stage3.get("checks", {}).get("reaction_feasibility_sha256", "")).upper() != hashes["reaction_feasibility"]:
        raise Stage6ValidationError("Stage 3 feasibility report hash disagrees with Stage 3 manifest")
    if str(stage3.get("checks", {}).get("reaction_sc_raw_sha256", "")).upper() != hashes["reaction_sc_raw"]:
        raise Stage6ValidationError("Stage 3 SC report hash disagrees with Stage 3 manifest")
    if str(stage5.get("tau")) != "0.8" or str(stage5.get("n0")) != "10" or stage5.get("precedent_mode") != "deployment":
        raise Stage6ValidationError("Stage 5 frozen tau/N0/mode are incompatible")
    return hashes, {
        "stage2_validation": stage2,
        "stage3_validation": stage3,
        "stage3_manifest": stage3_manifest,
        "stage4_manifest": stage4_manifest,
        "stage5_manifest": stage5,
    }


def _input_audit(paths: dict[str, Path], expected: dict[str, str]) -> dict[str, object]:
    audit: dict[str, object] = {}
    for label, path in paths.items():
        if not path.is_file():
            raise Stage6ValidationError(f"missing Stage 6 input {label}: {path}")
        actual = sha256(path)
        if actual != expected[label]:
            raise Stage6ValidationError(f"{label}: SHA256 mismatch expected={expected[label]} actual={actual} path={path}")
        frame = pd.read_parquet(path)
        audit[label] = {
            "path": str(path),
            "sha256": actual,
            "rows": int(len(frame)),
            "columns": frame.columns.tolist(),
        }
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reaction-steps", default=str(ROOT / "data/processed/reaction_steps_raw.parquet"))
    parser.add_argument("--feasibility", default=str(ROOT / "data/processed/reaction_feasibility.parquet"))
    parser.add_argument("--sc-raw", default=str(ROOT / "data/processed/reaction_sc_raw.parquet"))
    parser.add_argument("--precedent", default=str(ROOT / "data/processed/reaction_precedent.parquet"))
    parser.add_argument("--sc-normalized", default=str(ROOT / "data/processed/reaction_sc_normalized.parquet"))
    parser.add_argument("--output", default=str(ROOT / "data/processed/reaction_features.parquet"))
    parser.add_argument("--report", default=str(ROOT / "reports/stage6_feature_pipeline_report.json"))
    args = parser.parse_args()
    report: dict[str, object] = {
        "stage": 6,
        "status": "BLOCKED",
        "phase": "strict_merge_without_development_baseline",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "errors": [],
        "warnings": ["D_dev is added only by scripts/09_add_dev_baseline.py."],
    }
    try:
        expected, provenance = _expected_hashes()
        paths = {
            "reaction_steps_raw": _path(args.reaction_steps),
            "reaction_feasibility": _path(args.feasibility),
            "reaction_sc_raw": _path(args.sc_raw),
            "reaction_precedent": _path(args.precedent),
            "reaction_sc_normalized": _path(args.sc_normalized),
        }
        input_audit = _input_audit(paths, expected)
        base = pd.read_parquet(paths["reaction_steps_raw"])
        feasibility = pd.read_parquet(paths["reaction_feasibility"])
        sc_raw = pd.read_parquet(paths["reaction_sc_raw"])
        precedent = pd.read_parquet(paths["reaction_precedent"])
        sc_normalized = pd.read_parquet(paths["reaction_sc_normalized"])
        features, summary = build_features(
            base,
            feasibility,
            sc_raw,
            precedent,
            sc_normalized,
            stage5_manifest=provenance["stage5_manifest"],
            include_difficulty=False,
        )
        if features.columns.tolist() != FEATURE_COLUMNS:
            raise Stage6ValidationError("pre-baseline feature schema mismatch")
        destination = _path(args.output)
        if destination.exists():
            raise Stage6ValidationError(
                f"refusing to overwrite existing Stage 6 output before explicit baseline replacement: {destination}"
            )
        atomic_write_parquet(features, destination)
        round_trip = pd.read_parquet(destination)
        if round_trip.columns.tolist() != FEATURE_COLUMNS or len(round_trip) != len(base):
            raise Stage6ValidationError("pre-baseline output round-trip validation failed")
        report.update(
            {
                "status": "PASS",
                "input_audit": input_audit,
                "merge_audit": summary["merge"],
                "validation": summary["validation"],
                "output": {"path": str(destination), "sha256": sha256(destination), "rows": int(len(round_trip)), "columns": round_trip.columns.tolist()},
                "upstream_manifests": {
                    "stage2_validation": str(ROOT / "reports/stage2_validation.json"),
                    "stage3_validation": str(ROOT / "reports/stage3_validation.json"),
                    "stage3_manifest": str(ROOT / "data/generated/stage3_run_manifest.json"),
                    "stage4_manifest": str(ROOT / "reports/stage4_manifest.json"),
                    "stage5_manifest": str(ROOT / "reports/stage5_manifest.json"),
                },
            }
        )
    except Exception as exc:
        report["errors"] = [f"{type(exc).__name__}: {exc}"]
    json_dump_atomic(_path(args.report), report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
