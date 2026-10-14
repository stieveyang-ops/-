from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from rdkit import Chem

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "raw" / "targets.csv"
SMI = ROOT / "data" / "generated" / "targets.smi"
REPORT = ROOT / "reports" / "stage2_targets_validation.json"


def main() -> int:
    result = {
        "stage": 2,
        "status": "FAIL",
        "input_path": "data/raw/targets.csv",
        "target_count": 0,
        "errors": [],
        "warnings": [],
        "row_order_preserved": True,
        "canonical_targets": [],
    }
    records: list[tuple[str, str]] = []
    try:
        if not INPUT.is_file():
            result["status"] = "BLOCKED_TARGETS_MISSING"
            result["errors"].append("targets.csv does not exist")
        else:
            with INPUT.open(newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames != ["target_id", "target_smiles"]:
                    result["errors"].append(f"header must be exactly target_id,target_smiles; got {reader.fieldnames}")
                else:
                    seen_ids: set[str] = set()
                    seen_structures: set[str] = set()
                    for row_number, row in enumerate(reader, 2):
                        target_id = (row.get("target_id") or "").strip()
                        target_smiles = (row.get("target_smiles") or "").strip()
                        if not target_id:
                            result["errors"].append(f"row {row_number}: empty target_id")
                        elif target_id in seen_ids:
                            result["errors"].append(f"row {row_number}: duplicate target_id {target_id}")
                        if not target_smiles:
                            result["errors"].append(f"row {row_number}: empty target_smiles")
                            continue
                        mol = Chem.MolFromSmiles(target_smiles)
                        if mol is None:
                            result["errors"].append(f"row {row_number}: invalid/sanitize-failed SMILES {target_smiles}")
                            continue
                        canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
                        if canonical in seen_structures:
                            result["errors"].append(f"row {row_number}: duplicate canonical target structure {canonical}")
                        seen_ids.add(target_id)
                        seen_structures.add(canonical)
                        records.append((target_id, target_smiles))
                        result["canonical_targets"].append({"target_id": target_id, "canonical_smiles": canonical})
            result["target_count"] = len(records)
            if not result["errors"] and records:
                SMI.parent.mkdir(parents=True, exist_ok=True)
                SMI.write_text("\n".join(smiles for _, smiles in records) + "\n", encoding="utf-8")
            elif not records and not result["errors"]:
                result["errors"].append("target dataset is empty")
    except Exception as exc:
        result["errors"].append(f"exception: {type(exc).__name__}: {exc}")
    result["targets_csv_sha256"] = hashlib.sha256(INPUT.read_bytes()).hexdigest().upper() if INPUT.is_file() else None
    result["targets_smi_sha256"] = hashlib.sha256(SMI.read_bytes()).hexdigest().upper() if SMI.is_file() else None
    result["status"] = "PASS" if records and not result["errors"] else ("BLOCKED_TARGETS_MISSING" if not records and not result["errors"] else "FAIL")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
