from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from aiz_rd.route_extractor import extract_route_rows

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "data" / "generated" / "routes_raw.json"
TARGETS = ROOT / "data" / "raw" / "targets.csv"
OUT = ROOT / "data" / "processed" / "reaction_steps_raw.parquet"
PREVIEW = ROOT / "reports" / "reaction_steps_preview.csv"
REPORT = ROOT / "reports" / "stage2_extraction_report.json"


def main() -> int:
    result = {"status": "FAIL", "target_count": 0, "targets_with_routes": 0, "targets_without_routes": 0, "route_count_total": 0, "reaction_row_count": 0, "unique_reaction_hash_count": 0, "duplicate_reaction_hash_rows": 0, "invalid_molecule_count": 0, "route_topology_mismatch_count": 0, "routes_raw_sha256": None, "reaction_steps_raw_sha256": None, "warnings": [], "errors": []}
    try:
        df = pd.read_json(ROUTES, orient="table")
        target_df = pd.read_csv(TARGETS, dtype=str)
        result["target_count"] = len(target_df)
        if len(df) != len(target_df) or not {"target", "trees"}.issubset(df.columns):
            raise ValueError("routes_raw output alignment/schema failure")
        rows = []
        for idx, (out_target, target_row) in enumerate(zip(df.itertuples(index=False), target_df.itertuples(index=False)), 1):
            routes = out_target.trees
            result["route_count_total"] += len(routes)
            if routes: result["targets_with_routes"] += 1
            else: result["targets_without_routes"] += 1
            for route_index, route in enumerate(routes, 1):
                rows.extend(extract_route_rows(str(target_row.target_id), route_index, route))
        result["reaction_row_count"] = len(rows)
        result["unique_reaction_hash_count"] = len({r["reaction_hash"] for r in rows})
        result["duplicate_reaction_hash_rows"] = len(rows) - result["unique_reaction_hash_count"]
        out_df = pd.DataFrame(rows)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        out_df.to_parquet(OUT, index=False, engine="pyarrow", compression="zstd")
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        out_df.head(10)[["target_id", "route_id", "step_id", "reaction_smiles_raw", "reaction_smiles", "reaction_hash"]].to_csv(PREVIEW, index=False, encoding="utf-8")
        result["routes_raw_sha256"] = hashlib.sha256(ROUTES.read_bytes()).hexdigest().upper()
        result["reaction_steps_raw_sha256"] = hashlib.sha256(OUT.read_bytes()).hexdigest().upper()
        result["status"] = "PASS"
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    REPORT.parent.mkdir(parents=True, exist_ok=True); REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
