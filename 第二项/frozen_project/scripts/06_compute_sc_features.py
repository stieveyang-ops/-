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
from aizynthfinder.utils.sc_score import SCScore

from aiz_rd.chemistry import canonicalize_molecule_smiles, canonicalize_reaction, reaction_hash
from aiz_rd.route_extractor import _serialized_reactions
from aiz_rd.sc_feature import compute_delta_sc

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_COLUMNS = ["target_id", "route_id", "step_id", "reaction_hash", "product_smiles", "precursor_node_smiles_json", "precursor_count", "sc_product", "sc_precursor_values_json", "sc_precursor_max", "delta_sc"]


def sha256(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _recover_boundaries(routes_path: Path, src: pd.DataFrame) -> dict[str, tuple[str, list[str], str, str]]:
    routes_df = pd.read_json(routes_path, orient="table")
    targets_path = ROOT / "data" / "raw" / "targets.csv"
    targets_df = pd.read_csv(targets_path, dtype=str)
    if len(routes_df) != len(targets_df):
        raise RuntimeError("BLOCKED_PRECURSOR_BOUNDARY_MISMATCH: routes/targets row count")
    result = {}
    for target_row, target_info in zip(routes_df.itertuples(index=False), targets_df.itertuples(index=False)):
        target_id = str(target_info.target_id)
        for route_index, route in enumerate(target_row.trees, 1):
            serialized = _serialized_reactions(route)
            candidates = []
            for item in serialized:
                precursor, product, reaction = canonicalize_reaction(item.precursors_raw, item.product_raw)
                candidates.append((item, precursor, product, reaction))
            candidates.sort(key=lambda x: (x[0].reaction_depth, x[2], x[1], x[0].original_serialized_index))
            route_id = f"{target_id}__route_{route_index:03d}"
            for step_idx, (item, precursor, product, reaction) in enumerate(candidates, 1):
                step_id = f"{route_id}__step_{step_idx:03d}"
                # Canonicalize each complete child-node representation, but do
                # not split dot-disconnected components within a node.
                nodes = [canonicalize_molecule_smiles(node, f"precursor node {step_id}") for node in item.precursors_raw]
                result[step_id] = (product, nodes, precursor, reaction_hash(reaction))
    expected = src["step_id"].tolist()
    if set(result) != set(expected):
        missing = sorted(set(expected) - set(result)); extra = sorted(set(result) - set(expected))
        raise RuntimeError(f"BLOCKED_PRECURSOR_BOUNDARY_MISMATCH: missing={missing[:5]}, extra={extra[:5]}")
    for row in src.itertuples(index=False):
        product, nodes_raw, precursor, rhash = result[row.step_id]
        if product != row.product_smiles or precursor != row.precursor_smiles or rhash != row.reaction_hash:
            raise RuntimeError(f"BLOCKED_PRECURSOR_BOUNDARY_MISMATCH at {row.step_id}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "data/processed/reaction_steps_raw.parquet"))
    ap.add_argument("--routes", default=str(ROOT / "data/generated/routes_raw.json"))
    ap.add_argument("--environment-check", default=str(ROOT / "reports/environment_check.json"))
    ap.add_argument("--output", default=str(ROOT / "data/processed/reaction_sc_raw.parquet"))
    ap.add_argument("--report", default=str(ROOT / "reports/stage3_sc_report.json"))
    args = ap.parse_args()
    report = {"status": "BLOCKED", "errors": [], "warnings": []}
    output = Path(args.output); report_path = Path(args.report)
    try:
        src_path, routes_path = Path(args.input), Path(args.routes)
        env = json.loads(Path(args.environment_check).read_text(encoding="utf-8"))
        if env.get("overall_status") != "PASS" or env.get("scscore", {}).get("status") != "PASS": raise RuntimeError("BLOCKED_STAGE3_PREFLIGHT: Stage-1 SCScore status")
        model_path = Path(env["scscore"]["model_path"])
        if not model_path.is_file() or sha256(model_path) != env["scscore"]["sha256"].upper(): raise RuntimeError("BLOCKED_MODEL_DRIFT: SCScore model path/hash mismatch")
        src = pd.read_parquet(src_path)
        boundaries = _recover_boundaries(routes_path, src)
        model = SCScore(str(model_path))
        rows = []
        for row in src.itertuples(index=False):
            product, nodes_raw, _, _ = boundaries[row.step_id]
            result = compute_delta_sc(str(row.product_smiles), nodes_raw, model)
            rows.append({"target_id": str(row.target_id), "route_id": str(row.route_id), "step_id": str(row.step_id), "reaction_hash": str(row.reaction_hash), "product_smiles": str(row.product_smiles), "precursor_node_smiles_json": json.dumps(nodes_raw, ensure_ascii=False, separators=(",", ":")), "precursor_count": len(nodes_raw), "sc_product": float(result.sc_product), "sc_precursor_values_json": json.dumps(list(result.sc_precursor_values), ensure_ascii=False, separators=(",", ":")), "sc_precursor_max": float(result.sc_precursor_max), "delta_sc": float(result.delta_sc)})
        out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        if out["step_id"].tolist() != src["step_id"].tolist() or out["reaction_hash"].tolist() != src["reaction_hash"].tolist(): raise RuntimeError("SC output alignment mismatch")
        numeric = ["sc_product", "sc_precursor_max", "delta_sc"]
        if not all(out[c].map(lambda x: math.isfinite(float(x))).all() for c in numeric): raise RuntimeError("Non-finite SC value")
        for value_json, max_value in zip(out["sc_precursor_values_json"], out["sc_precursor_max"]):
            vals = json.loads(value_json)
            if not vals or abs(max(vals) - float(max_value)) > 1e-12: raise RuntimeError("SC precursor max identity failed")
        output.parent.mkdir(parents=True, exist_ok=True); report_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=str(output.parent)); os.close(fd); tmp = Path(tmp_name)
        try:
            out.to_parquet(tmp, index=False, engine="pyarrow", compression="zstd")
            check = pd.read_parquet(tmp)
            if len(check) != len(src): raise RuntimeError("SC temporary output row count mismatch")
            os.replace(tmp, output)
        finally:
            if tmp.exists(): tmp.unlink()
        sp, sm, ds = out["sc_product"].astype(float), out["sc_precursor_max"].astype(float), out["delta_sc"].astype(float)
        report.update({"status": "PASS", "reaction_row_count": len(out), "scscore_model_path": str(model_path), "scscore_model_sha256": sha256(model_path), "implementation": "aizynthfinder.utils.sc_score.SCScore", "sc_product_min": float(sp.min()), "sc_product_max": float(sp.max()), "sc_precursor_max_min": float(sm.min()), "sc_precursor_max_max": float(sm.max()), "delta_sc_min": float(ds.min()), "delta_sc_max": float(ds.max()), "delta_sc_mean": float(ds.mean()), "negative_delta_sc_count": int((ds < 0).sum()), "precursor_boundary_source": "routes_raw_reconstruction", "nan_count": 0, "inf_count": 0, "out_of_scscore_range_count": int(((sp < 1 - 1e-6) | (sp > 5 + 1e-6) | (sm < 1 - 1e-6) | (sm > 5 + 1e-6)).sum()), "output_sha256": sha256(output), "input_sha256": sha256(src_path), "routes_raw_sha256": sha256(routes_path), "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    report_path.parent.mkdir(parents=True, exist_ok=True); report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False)); return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
