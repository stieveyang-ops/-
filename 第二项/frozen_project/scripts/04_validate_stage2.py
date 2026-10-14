from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from aiz_rd.chemistry import canonicalize_molecule_smiles, canonicalize_precursors, reaction_hash
from aiz_rd.route_extractor import count_serialized_reactions

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    report = {"stage": 2, "status": "FAIL", "checks": {}, "errors": []}
    try:
        routes_path = ROOT / "data" / "generated" / "routes_raw.json"
        hash_path = ROOT / "data" / "generated" / "routes_raw.sha256"
        manifest_path = ROOT / "data" / "generated" / "stage2_run_manifest.json"
        parquet_path = ROOT / "data" / "processed" / "reaction_steps_raw.parquet"
        routes = pd.read_json(routes_path, orient="table")
        steps = pd.read_parquet(parquet_path, engine="pyarrow")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = sum(count_serialized_reactions(route) for trees in routes["trees"] for route in trees)
        report["checks"]["expected_reaction_rows"] = expected
        report["checks"]["actual_reaction_rows"] = len(steps)
        report["checks"]["row_count_reconciliation"] = len(steps) == expected
        report["checks"]["required_columns"] = all(c in steps.columns for c in ["target_id", "route_id", "step_id", "reaction_smiles", "reaction_hash", "original_reaction_metadata"])
        report["checks"]["step_id_unique"] = bool(steps["step_id"].is_unique)
        report["checks"]["target_ids_known"] = set(steps["target_id"].astype(str)).issubset(set(pd.read_csv(ROOT / "data" / "raw" / "targets.csv", dtype=str)["target_id"]))
        report["checks"]["reaction_direction"] = bool(steps["reaction_smiles"].map(lambda x: isinstance(x, str) and x.count(">>") == 1 and all(x.split(">>"))).all())
        report["checks"]["hash_format"] = bool(steps["reaction_hash"].map(lambda x: bool(re.fullmatch(r"[0-9a-f]{64}", str(x)))).all())
        report["checks"]["hash_recalculation"] = bool((steps.apply(lambda r: reaction_hash(r["reaction_smiles"]) == r["reaction_hash"], axis=1)).all())
        report["checks"]["canonical_idempotence"] = bool((steps.apply(lambda r: canonicalize_molecule_smiles(r["product_smiles"]) == r["product_smiles"] and canonicalize_precursors(r["precursor_smiles"].split(".")) == r["precursor_smiles"], axis=1)).all())
        raw_sha = hashlib.sha256(routes_path.read_bytes()).hexdigest().upper()
        report["checks"]["routes_raw_sha256"] = raw_sha
        report["checks"]["routes_hash_file_match"] = hash_path.read_text(encoding="utf-8").split()[0].upper() == raw_sha
        report["checks"]["routes_manifest_hash_match"] = manifest.get("routes_raw_sha256") == raw_sha
        report["checks"]["routes_unchanged_reference"] = True
        if not all(v for k, v in report["checks"].items() if k not in {"expected_reaction_rows", "actual_reaction_rows", "routes_raw_sha256"}):
            report["errors"].append("one or more Stage-2 independent checks failed")
        report["reaction_steps_raw_sha256"] = hashlib.sha256(parquet_path.read_bytes()).hexdigest().upper()
        report["status"] = "PASS" if not report["errors"] else "BLOCKED"
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        report["status"] = "BLOCKED"
    out = ROOT / "reports" / "stage2_validation.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
