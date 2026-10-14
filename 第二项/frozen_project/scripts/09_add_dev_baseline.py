"""Add the fixed Stage 6 DEVELOPMENT BASELINE atomically."""

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

from aiz_rd.dev_baseline import BASELINE_LABEL, add_dev_baseline, run_boundary_and_monotonicity_tests  # noqa: E402
from aiz_rd.feature_pipeline import (  # noqa: E402
    FINAL_COLUMNS,
    Stage6ValidationError,
    atomic_write_parquet,
    json_dump_atomic,
    sha256,
    validate_feature_values,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default=str(ROOT / "data/processed/reaction_features.parquet"))
    parser.add_argument("--report", default=str(ROOT / "reports/stage6_feature_pipeline_report.json"))
    args = parser.parse_args()
    features_path = Path(args.features).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    report: dict[str, object] = {"stage": 6, "phase": "development_baseline", "status": "BLOCKED", "errors": []}
    try:
        if not features_path.is_file():
            raise Stage6ValidationError(f"missing pre-baseline feature table: {features_path}")
        frame = pd.read_parquet(features_path)
        validation = validate_feature_values(frame, require_difficulty=False)
        boundary = run_boundary_and_monotonicity_tests()
        old_hash = sha256(features_path)
        result = add_dev_baseline(frame)
        result = result[FINAL_COLUMNS]
        final_validation = validate_feature_values(result, require_difficulty=True)
        # atomic_write_parquet performs a temporary write, round-trip, then an
        # atomic replacement.  This replacement is intentional: it appends the
        # approved development-only column after the pre-baseline QA passed.
        atomic_write_parquet(result, features_path)
        check = pd.read_parquet(features_path)
        if check.columns.tolist() != FINAL_COLUMNS or len(check) != len(result):
            raise Stage6ValidationError("final feature output round-trip mismatch")
        report.update(
            {
                "status": "PASS",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "baseline_label": BASELINE_LABEL,
                "weights": {"d_feas": 0.45, "d_prec": 0.40, "d_sc": 0.15},
                "pre_baseline_validation": validation,
                "boundary_and_monotonicity_tests": boundary,
                "final_validation": final_validation,
                "output": {
                    "path": str(features_path),
                    "old_prebaseline_sha256": old_hash,
                    "sha256": sha256(features_path),
                    "rows": int(len(check)),
                    "columns": check.columns.tolist(),
                    "intentional_atomic_replacement": True,
                },
            }
        )
    except Exception as exc:
        report["errors"] = [f"{type(exc).__name__}: {exc}"]
    json_dump_atomic(report_path, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
