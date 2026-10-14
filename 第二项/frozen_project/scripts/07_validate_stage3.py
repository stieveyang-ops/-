from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import rdkit
from importlib.metadata import version as package_version

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "data/processed/reaction_steps_raw.parquet"))
    ap.add_argument("--feasibility", default=str(ROOT / "data/processed/reaction_feasibility.parquet"))
    ap.add_argument("--sc", default=str(ROOT / "data/processed/reaction_sc_raw.parquet"))
    ap.add_argument("--routes", default=str(ROOT / "data/generated/routes_raw.json"))
    ap.add_argument("--stage2-manifest", default=str(ROOT / "data/generated/stage2_run_manifest.json"))
    ap.add_argument("--stage2-validation", default=str(ROOT / "reports/stage2_validation.json"))
    ap.add_argument("--environment-check", default=str(ROOT / "reports/environment_check.json"))
    ap.add_argument("--report", default=str(ROOT / "reports/stage3_validation.json"))
    args = ap.parse_args()
    report = {"status": "FAIL", "errors": [], "warnings": [], "checks": {}}
    try:
        inp, feas_path, sc_path, routes_path = map(Path, (args.input, args.feasibility, args.sc, args.routes))
        src = pd.read_parquet(inp); feas = pd.read_parquet(feas_path); sc = pd.read_parquet(sc_path)
        report["checks"]["reaction_steps_raw_sha256"] = sha256(inp)
        report["checks"]["reaction_feasibility_sha256"] = sha256(feas_path)
        report["checks"]["reaction_sc_raw_sha256"] = sha256(sc_path)
        report["checks"]["row_counts"] = {"input": len(src), "feasibility": len(feas), "sc": len(sc)}
        if not (len(src) == len(feas) == len(sc)): raise RuntimeError("row count mismatch")
        if not (src.step_id.is_unique and feas.step_id.is_unique and sc.step_id.is_unique): raise RuntimeError("step_id not unique")
        if feas.step_id.tolist() != src.step_id.tolist() or sc.step_id.tolist() != src.step_id.tolist(): raise RuntimeError("step_id alignment mismatch")
        if feas.reaction_hash.tolist() != src.reaction_hash.tolist() or sc.reaction_hash.tolist() != src.reaction_hash.tolist(): raise RuntimeError("reaction_hash alignment mismatch")
        p, d = feas.p_feas.astype(float), feas.d_feas.astype(float)
        report["checks"]["p_feas_range"] = bool(((p >= 0) & (p <= 1)).all())
        report["checks"]["d_feas_identity"] = bool(((d - (1-p)).abs() <= 1e-12).all())
        report["checks"]["cutoff_contract"] = bool((feas.quickfilter_feasible_flag.astype(bool) == (p >= feas.quickfilter_cutoff.astype(float))).all())
        for name, series in [("p_feas",p),("d_feas",d),("sc_product",sc.sc_product.astype(float)),("sc_precursor_max",sc.sc_precursor_max.astype(float)),("delta_sc",sc.delta_sc.astype(float))]:
            if not series.map(math.isfinite).all(): raise RuntimeError(f"non-finite {name}")
        max_ok = True; delta_ok = True; count_ok = True
        for vals_json, count, max_val, prod, delta in zip(sc.sc_precursor_values_json, sc.precursor_count, sc.sc_precursor_max, sc.sc_product, sc.delta_sc):
            vals = json.loads(vals_json)
            max_ok &= len(vals) == int(count) and len(vals) >= 1 and abs(max(vals)-float(max_val)) <= 1e-12
            delta_ok &= abs(float(delta) - (float(prod)-float(max_val))) <= 1e-12
            count_ok &= len(vals) == int(count)
        forbidden = {"p_prec","d_prec","d_sc","normalized_delta_sc","difficulty_dev","reaction_difficulty","uncertainty","rxnfp"}
        report["checks"].update({"sc_precursor_max_identity": bool(max_ok), "delta_sc_identity": bool(delta_ok), "precursor_count_identity": bool(count_ok), "no_later_stage_fields": not bool((set(feas.columns) | set(sc.columns)) & forbidden)})
        env = json.loads(Path(args.environment_check).read_text(encoding="utf-8"))
        report["checks"]["model_hashes_match_stage1"] = (sha256(Path(env["quick_filter"]["model_path"])) == env["quick_filter"]["sha256"].upper() and sha256(Path(env["scscore"]["model_path"])) == env["scscore"]["sha256"].upper())
        stage2 = json.loads(Path(args.stage2_manifest).read_text(encoding="utf-8"))
        report["checks"]["routes_hash_matches_stage2"] = sha256(routes_path) == stage2["routes_raw_sha256"].upper()
        stage2_validation = json.loads(Path(args.stage2_validation).read_text(encoding="utf-8"))
        recorded_input_hash = stage2_validation.get("reaction_steps_raw_sha256")
        report["checks"]["input_hash_matches_stage2"] = bool(recorded_input_hash) and sha256(inp) == str(recorded_input_hash).upper()
        if not all(report["checks"].values()): raise RuntimeError("one or more validation checks failed")
        feasibility_report = json.loads((ROOT / "reports/stage3_feasibility_report.json").read_text(encoding="utf-8"))
        sc_report = json.loads((ROOT / "reports/stage3_sc_report.json").read_text(encoding="utf-8"))
        manifest = {
            "stage": 3,
            "schema_version": "stage3-feature-manifest-v1",
            "input_reaction_steps": "data/processed/reaction_steps_raw.parquet",
            "input_reaction_steps_sha256": sha256(inp),
            "routes_raw_sha256": sha256(routes_path),
            "aizynthfinder_version": package_version("aizynthfinder"),
            "rdkit_version": rdkit.__version__,
            "quickfilter": {"key": feasibility_report["quickfilter_key"], "model_path": env["quick_filter"]["model_path"], "model_sha256": env["quick_filter"]["sha256"], "filter_cutoff": feasibility_report["filter_cutoff"]},
            "scscore": {"model_path": env["scscore"]["model_path"], "model_sha256": env["scscore"]["sha256"], "implementation": "aizynthfinder.utils.sc_score.SCScore"},
            "definitions": {"d_feas": "1 - p_feas", "sc_precursor": "max SC over AiZynthFinder precursor molecule nodes", "delta_sc": "sc_product - sc_precursor_max", "delta_sc_normalized": False},
            "output_feasibility_sha256": sha256(feas_path),
            "output_sc_raw_sha256": sha256(sc_path),
            "reaction_row_count": len(src),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        (ROOT / "data/generated/stage3_run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        preview = src[["target_id", "route_id", "step_id", "reaction_smiles", "reaction_hash"]].join(feas[["p_feas", "d_feas"]]).join(sc[["sc_product", "sc_precursor_max", "delta_sc", "precursor_count"]])
        preview.head(30).to_csv(ROOT / "reports/stage3_features_preview.csv", index=False, encoding="utf-8-sig")
        report["status"] = "PASS"
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False)); return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
