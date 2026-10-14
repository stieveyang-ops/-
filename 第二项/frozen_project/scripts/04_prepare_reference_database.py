"""Import and clean the authorized ORD protobuf Parquet release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from ord_schema.proto import reaction_pb2

from aiz_rd.chemistry import canonicalize_reaction, reaction_hash
from aiz_rd.precedent import ord_message_to_transformation

ROOT = Path(__file__).resolve().parents[1]
RAW_COLUMNS = ["reference_source_record_id", "raw_reaction_smiles", "source", "input_row_number", "source_file_sha256"]
CLEAN_COLUMNS = ["reference_id", "reaction_smiles", "reaction_hash", "source", "source_record_ids_json", "duplicate_count"]
REJECT_COLUMNS = ["input_row_number", "reference_source_record_id", "raw_reaction_smiles", "source", "rejection_reason", "error_type", "error_message_truncated"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def cfg_load(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def reject(row_number, record_id, raw, reason, exc=None):
    return {"input_row_number": int(row_number), "reference_source_record_id": record_id, "raw_reaction_smiles": raw, "source": "ord", "rejection_reason": reason, "error_type": type(exc).__name__ if exc else "", "error_message_truncated": str(exc)[:500] if exc else ""}


def atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        df.to_parquet(tmp_path, index=False, engine="pyarrow", compression="zstd")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--config", default=str(ROOT / "config/precedent.yml")); args = ap.parse_args()
    cfg = cfg_load(Path(args.config)); ref = cfg["reference"]
    report = {"status": "BLOCKED", "source_type": ref.get("source_type"), "source_name": ref.get("source_name"), "input_path": ref.get("input_path"), "errors": [], "warnings": []}
    try:
        if ref.get("source_type") != "ord": raise RuntimeError("BLOCKED_SOURCE_SCHEMA_AMBIGUOUS: source_type must be ord")
        source_dir = Path(ref["input_path"]); manifest_path = Path(ref["manifest_path"])
        if not source_dir.is_dir() or not manifest_path.is_file(): raise RuntimeError("BLOCKED_REFERENCE_FILE_UNREADABLE: ORD directory/manifest missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")); files = manifest.get("files", [])
        if not files: raise RuntimeError("BLOCKED_REFERENCE_FILE_UNREADABLE: empty ORD manifest")
        resolved = []
        for item in files:
            path = Path(item["local_file"])
            if not path.is_file() or path.stat().st_size != int(item["size"]) or sha256(path).lower() != str(item["sha256"]).lower():
                raise RuntimeError(f"BLOCKED_REFERENCE_FILE_UNREADABLE: manifest mismatch {path}")
            resolved.append((path, str(item["sha256"]).upper()))
        resolved.sort(key=lambda x: str(x[0]).lower())
        file_hash_manifest = hashlib.sha256("\n".join(f"{p.name}\t{h}" for p,h in resolved).encode()).hexdigest().upper()
        raw_rows=[]; clean_groups={}; rejected=[]; row_number=0
        payload_column = ref.get("payload_column")
        if ref.get("reaction_column") is not None:
            raise RuntimeError("BLOCKED_SOURCE_SCHEMA_AMBIGUOUS: native ORD reaction_column must be null")
        if not payload_column:
            raise RuntimeError("BLOCKED_SOURCE_SCHEMA_AMBIGUOUS: native ORD payload_column is required")
        for path, file_hash in resolved:
            frame = pd.read_parquet(path, columns=[ref["source_id_column"], payload_column])
            if ref["source_id_column"] not in frame or payload_column not in frame: raise RuntimeError("BLOCKED_SOURCE_SCHEMA_AMBIGUOUS: ORD columns missing")
            for item in frame.itertuples(index=False, name=None):
                row_number += 1; record_id, payload = item; raw = None
                raw_rows.append({"reference_source_record_id": str(record_id) if record_id is not None else None, "raw_reaction_smiles": None, "source": "ord", "input_row_number": row_number, "source_file_sha256": file_hash})
                try:
                    if not isinstance(payload, (bytes, bytearray, memoryview)): raise TypeError("reaction payload is not protobuf bytes")
                    msg = reaction_pb2.Reaction(); msg.ParseFromString(bytes(payload))
                    trans = ord_message_to_transformation(msg); raw = trans
                    raw_rows[-1]["raw_reaction_smiles"] = raw
                    reactants, products = trans.split(">>", 1)
                    precursor, product, canonical = canonicalize_reaction(reactants.split("."), products)
                    rhash = reaction_hash(canonical)
                    group = clean_groups.setdefault(rhash, {"reaction_smiles": canonical, "reaction_hash": rhash, "sources": set(), "ids": set(), "count": 0})
                    group["sources"].add("ord"); group["count"] += 1
                    if record_id is not None and str(record_id): group["ids"].add(str(record_id))
                except Exception as exc:
                    reason = "MISSING_REACTION" if payload is None else "RDKIT_PARSE_FAILED" if "parse" in str(exc).lower() or "sanitize" in str(exc).lower() else "CANONICALIZATION_FAILED" if raw else "MALFORMED_REACTION"
                    rejected.append(reject(row_number, str(record_id) if record_id is not None else None, raw, reason, exc))
        if not clean_groups: raise RuntimeError("BLOCKED_REFERENCE_COUNT_MISMATCH: clean corpus is empty")
        clean_rows=[]
        for rhash, group in clean_groups.items():
            clean_rows.append({"reference_id": "ref_" + rhash, "reaction_smiles": group["reaction_smiles"], "reaction_hash": rhash, "source": "|".join(sorted(group["sources"])), "source_record_ids_json": json.dumps(sorted(group["ids"]), ensure_ascii=False, separators=(",", ":")), "duplicate_count": int(group["count"])})
        clean_rows.sort(key=lambda x: x["reaction_hash"])
        raw_df=pd.DataFrame(raw_rows, columns=RAW_COLUMNS); clean_df=pd.DataFrame(clean_rows, columns=CLEAN_COLUMNS); rejected_df=pd.DataFrame(rejected, columns=REJECT_COLUMNS)
        out_dir=ROOT/"data/reference"; out_dir.mkdir(parents=True, exist_ok=True); (ROOT/"reports").mkdir(exist_ok=True)
        raw_path=out_dir/"reference_reactions.parquet"; clean_path=out_dir/"reference_reactions_clean.parquet"; rej_path=out_dir/"reference_reactions_rejected.parquet"
        atomic_parquet(raw_df, raw_path); atomic_parquet(clean_df, clean_path); atomic_parquet(rejected_df, rej_path)
        n_input=row_number; n_rej=len(rejected_df); n_valid=n_input-n_rej; n_clean=len(clean_df); n_dups=n_valid-n_clean
        if n_input != n_rej+n_valid or n_valid != n_clean+n_dups: raise RuntimeError("BLOCKED_REFERENCE_COUNT_MISMATCH")
        report.update({"status":"PASS","source_type":"ord","source_name":ref["source_name"],"input_path":str(source_dir),"input_manifest_path":str(manifest_path),"input_manifest_sha256":sha256(manifest_path),"input_file_count":len(resolved),"input_file_manifest_sha256":file_hash_manifest,"reaction_column":None,"payload_column":payload_column,"source_id_column":ref.get("source_id_column"),"reaction_representation":"Native ORD Reaction protobuf bytes converted to transformation-only reactants>>products through ord-schema typed-role helpers; no reaction SMILES column was assumed.","ord_schema_helper":"ord_schema.message_helpers.smiles_from_compound","n_input":n_input,"n_valid_before_dedup":n_valid,"n_clean_unique":n_clean,"n_exact_duplicates_removed":n_dups,"n_rejected":n_rej,"rejection_counts":dict(Counter(rejected_df.rejection_reason.tolist())),"source_counts_before_dedup":{"ord":n_valid},"source_counts_after_dedup":{"ord":n_clean},"canonicalizer_file_sha256":sha256(ROOT/"src/aiz_rd/chemistry.py"),"raw_import_parquet_sha256":sha256(raw_path),"clean_parquet_sha256":sha256(clean_path),"rejected_parquet_sha256":sha256(rej_path),"license_or_terms":ref.get("license_or_terms"),"timestamp_utc":datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    atomic_json(ROOT/"reports/reference_database_report.json", report)
    print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report["status"]=="PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
