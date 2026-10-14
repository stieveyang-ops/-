from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from aizynthfinder.aizynthfinder import AiZynthExpander

from aiz_rd.feasibility import compute_feasibility


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_COLUMNS = ["target_id", "route_id", "step_id", "reaction_hash", "product_smiles", "precursor_smiles"]
OUTPUT_COLUMNS = [
    "target_id", "route_id", "step_id", "reaction_hash", "p_feas", "d_feas",
    "quickfilter_feasible_flag", "quickfilter_cutoff", "quickfilter_key",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_stage1(env_path: Path) -> dict:
    report = json.loads(env_path.read_text(encoding="utf-8"))
    if report.get("overall_status") != "PASS" or report.get("quick_filter", {}).get("status") != "PASS":
        raise RuntimeError("BLOCKED_STAGE3_PREFLIGHT: Stage-1 environment/QuickFilter status is not PASS")
    return report


def _select_filter(config_path: Path, env: dict):
    expander = AiZynthExpander(configfile=str(config_path))
    available = expander.filter_policy.items
    expected_key = env["quick_filter"].get("key")
    if isinstance(expected_key, list):
        expected_key = expected_key[0] if len(expected_key) == 1 else None
    if len(available) != 1 or (expected_key and available[0] != expected_key):
        raise RuntimeError(f"BLOCKED_AMBIGUOUS_QUICKFILTER: available={available}, expected={expected_key}")
    key = available[0]
    filt = expander.filter_policy[key]
    model_path = Path(env["quick_filter"]["model_path"])
    if not model_path.is_file() or sha256(model_path) != env["quick_filter"]["sha256"].upper():
        raise RuntimeError("BLOCKED_MODEL_DRIFT: QuickFilter model path/hash mismatch")
    config_model = Path(getattr(filt, "_kwargs", {}).get("model", model_path))
    if config_model.resolve() != model_path.resolve():
        raise RuntimeError(f"BLOCKED_MODEL_DRIFT: production config model differs: {config_model} != {model_path}")
    return key, filt, model_path


def _canonical_equivalence_audit(src: pd.DataFrame, filt, limit: int = 20) -> tuple[int, float]:
    """Compare raw Stage-2 strings with their stored canonical strings."""
    max_diff = 0.0
    selected = src.sort_values("step_id").head(limit)
    for row in selected.itertuples(index=False):
        raw = compute_feasibility(row.product_smiles_raw, row.precursor_smiles_raw, filt).p_feas
        canonical = compute_feasibility(row.product_smiles, row.precursor_smiles, filt).p_feas
        max_diff = max(max_diff, abs(raw - canonical))
        if abs(raw - canonical) > 1e-7:
            raise RuntimeError(f"QuickFilter raw/canonical equivalence failed at {row.step_id}: {raw} vs {canonical}")
    return len(selected), max_diff


def _validate_output(out: pd.DataFrame, src: pd.DataFrame, cutoff: float) -> None:
    if list(out.columns) != OUTPUT_COLUMNS or len(out) != len(src):
        raise RuntimeError("Stage3 feasibility output schema/row-count mismatch")
    if out["step_id"].tolist() != src["step_id"].tolist() or out["reaction_hash"].tolist() != src["reaction_hash"].tolist():
        raise RuntimeError("Stage3 feasibility step/hash alignment mismatch")
    for col in ["p_feas", "d_feas"]:
        vals = out[col].astype(float)
        if not vals.map(math.isfinite).all() or not ((vals >= 0) & (vals <= 1)).all():
            raise RuntimeError(f"Invalid feasibility values in {col}")
    if not ((out["d_feas"] - (1.0 - out["p_feas"]).astype(float)).abs() <= 1e-12).all():
        raise RuntimeError("d_feas identity failed")
    if not (out["quickfilter_feasible_flag"].astype(bool) == (out["p_feas"] >= cutoff)).all():
        raise RuntimeError("QuickFilter cutoff contract failed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "data/processed/reaction_steps_raw.parquet"))
    ap.add_argument("--production-config", default=str(ROOT / "config/config_production.yml"))
    ap.add_argument("--environment-check", default=str(ROOT / "reports/environment_check.json"))
    ap.add_argument("--output", default=str(ROOT / "data/processed/reaction_feasibility.parquet"))
    ap.add_argument("--report", default=str(ROOT / "reports/stage3_feasibility_report.json"))
    args = ap.parse_args()
    report = {"status": "BLOCKED", "errors": [], "warnings": []}
    output = Path(args.output); report_path = Path(args.report)
    try:
        src_path = Path(args.input); env_path = Path(args.environment_check)
        env = _load_stage1(env_path)
        src = pd.read_parquet(src_path)
        if len(src) == 0 or any(c not in src.columns for c in REQUIRED_COLUMNS):
            raise RuntimeError("BLOCKED_STAGE3_PREFLIGHT: reaction_steps_raw schema/row count")
        key, filt, model_path = _select_filter(Path(args.production_config), env)
        cutoff = float(filt.filter_cutoff)
        canonical_checked, canonical_max_diff = _canonical_equivalence_audit(src, filt)
        rows = []
        for row in src.itertuples(index=False):
            result = compute_feasibility(row.product_smiles, row.precursor_smiles, filt)
            rows.append({"target_id": str(row.target_id), "route_id": str(row.route_id), "step_id": str(row.step_id), "reaction_hash": str(row.reaction_hash), "p_feas": float(result.p_feas), "d_feas": float(result.d_feas), "quickfilter_feasible_flag": bool(result.feasible_flag), "quickfilter_cutoff": cutoff, "quickfilter_key": key})
        out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        _validate_output(out, src, cutoff)
        output.parent.mkdir(parents=True, exist_ok=True); report_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=str(output.parent)); os.close(fd)
        tmp = Path(tmp_name)
        try:
            out.to_parquet(tmp, index=False, engine="pyarrow", compression="zstd")
            check = pd.read_parquet(tmp); _validate_output(check, src, cutoff)
            os.replace(tmp, output)
        finally:
            if tmp.exists(): tmp.unlink()
        probs = out["p_feas"].astype(float); ds = out["d_feas"].astype(float)
        report.update({"status": "PASS", "reaction_row_count": len(out), "quickfilter_key": key, "quickfilter_model_path": str(model_path), "quickfilter_model_sha256": sha256(model_path), "filter_cutoff": cutoff, "p_feas_min": float(probs.min()), "p_feas_max": float(probs.max()), "p_feas_mean": float(probs.mean()), "d_feas_min": float(ds.min()), "d_feas_max": float(ds.max()), "boolean_feasible_count": int(out["quickfilter_feasible_flag"].sum()), "boolean_infeasible_count": int((~out["quickfilter_feasible_flag"]).sum()), "canonical_equivalence_checked": canonical_checked, "canonical_equivalence_max_abs_diff": canonical_max_diff, "nan_count": 0, "inf_count": 0, "output_sha256": sha256(output), "input_sha256": sha256(src_path), "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        if output.with_suffix(output.suffix + ".tmp").exists(): output.with_suffix(output.suffix + ".tmp").unlink()
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
