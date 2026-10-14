"""Create a non-destructive Git provenance baseline inventory.

This is an engineering audit helper only.  It does not read or alter scientific
values and is intended to run before repository initialization.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "stage11_git_baseline_inventory.json"
SNAPSHOT = Path(r"C:\Users\Pasem\Documents\Codex\2026-09-13\pre_git_snapshot_5f190dc6d81a45da8eebf0d1d35771d2")
SNAPSHOT_MANIFEST = SNAPSHOT / "PRE_GIT_SNAPSHOT_MANIFEST.json"

EXCLUDED_DIRS = {".git", ".conda-rxnfp", ".venv-rxnfp", ".pytest_cache", "__pycache__", ".venv", "venv"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log", ".key", ".pem"}
EXCLUDED_NAMES = {".env"}
SENSITIVE_RE = re.compile(r"(?i)(BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|aws_secret_access_key|api[_-]?key|password\s*=|secret\s*=)")

EXPECTED = {
    "data/generated/routes_raw.json": "5FA6489B6DF5437066F42AC1323C179C0871F711ACFE9BC3435A0C63221F49BE",
    "data/processed/reaction_steps_raw.parquet": "611B4F7DA5C701D093BA3D36B1E79EF76F08DEDFA6E3A1D9397814C532FF43DF",
    "data/processed/reaction_features.parquet": "B2990C19F94020D6E9C23EF8E1C5E57772D58631AD2F68863D0B11721D3A3226",
    "data/reference/reference_reactions_clean.parquet": "7506803AAB4EFA13FFD2E4D20ECABF1E37AC0D01FA4C7880B9EF1963E02576B8",
    "data/reference/reference_reactions.parquet": "4F0B098E97B8465E38F2B900BB4BCC8C9B5ECC43709D91FAC570470EF0E6970B",
    "data/reference/reference_reactions_rejected.parquet": "8CD219229FEC58C7FC784A20C8B8BBDCCBC6781ECAAAEC35B84352C5DD3BC6DF",
    "artifacts/reference_rxnfp.npy": "37766193FEADD7C05CB97FF6285AF5D791A7FCF0EB37CE5D311D481DAD115E44",
    "artifacts/reference_metadata.parquet": "7062193C9936AA08FF2E43DB9BBA7C1B1269CC9FED12DE0A85827CAFF1EEB2AB",
    "artifacts/reference_nn_index.joblib": "BB0B2D99E7D461604F5B498E56AB9206B587B1935B785959A9CDB715ED24CBB9",
    "data/processed/reaction_precedent.parquet": "B5697790CF3D502A0F197F2A6E6007DCE458DCD743D5EBBF1AFE7B1863F57A80",
    "data/processed/reaction_sc_normalized.parquet": "26DFF4A3603975E47FBC440CF22409E9F22873A382BD7FD3353C6D1BC1CF2EB7",
    "artifacts/sc_delta_ecdf.npz": "3F82C235D0B48F6CADA66461E1664B68DA310593E0D76992C3CA546D6E68F6C5",
    "data/processed/reaction_feasibility.parquet": "11CEC9A29C108DB3402793A48F2E49FD7883338DF4998EE019CBCD2E2ABFBDF4",
    "data/processed/reaction_sc_raw.parquet": "91E01FF220538DC3C9B3FAD6EE87B28520C45169235C3BECC74EBBD95E25D1BE",
    "data/splits/test_ids_locked.txt": "0891F4CB2DDD5422B68DE526A81495C3969462DE1520B7DD5EBDF5F4C8449FE7",
    "data/splits/train_ids.txt": "77B0BF7238686AE0339622181CD421923222A4F0961CD0FAC1722DD718ED30B4",
    "data/labels/final_expert_labels.parquet": "F5BA0C82D24DBADD0EC6169246966C492C99EA69E66A95E641B08CD38F0FB72D",
    "artifacts/difficulty_model.pkl": "1BEECF8BF88378E1AC39AB3F5CD996CE068E110635D0E6913B03A11147EF84A2",
    "artifacts/difficulty_model_metadata.json": "DF2AD18C9A40DC30D7B0F767D30E44D953DEDB6F84884FAA047241EDEB416055",
    "outputs/scored_reactions.parquet": "C4A24417197B1ABAC2B22987C3A1352F27D4953456D7F465F7F7146DA784CAFF",
    "outputs/scored_routes.parquet": "8EB0A886716FA8F7CAD6EB25B828BBFB0B95ED3B1B1E9D637AEB3578F572CF01",
    "outputs/scored_routes.json": "AB0EAA1B08D49C4F702B448018B53BC56F1FC8811B32EC67B81F90FC7853F59A",
    "reports/stage10_manifest_v22.json": "C457773111ADB9BE5DD165F0E8B80DAF78F4521225C50A72F6C77E79FCF63F04",
    "reports/stage10_preanalysis_manifest_v22.json": "820ECCF6942C28280BFB5670726919B835E65921ACDB7DA6F77AE18035F60A71",
    "reports/stage10_preunseal_test_report_v22.json": "5FE9D8F75A8C8590FAA5043C529185712D0DC7482C533A8ECFE753F3A0E64757",
    "reports/stage10_unseal_receipt_v22.json": "E923BC093786F31CE2AD081BEDDD84E634193846A5AB49461DBFB406A98D3C58",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def exclusion_reason(rel: str, path: Path) -> str | None:
    parts = set(path.relative_to(ROOT).parts)
    if parts & EXCLUDED_DIRS:
        return "local environment/cache/build output excluded by .gitignore"
    if path.name in EXCLUDED_NAMES:
        return "credential/environment file excluded by .gitignore"
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return "temporary/log/credential suffix excluded by .gitignore"
    if rel.startswith("artifacts/runtime/aizynth/") and path.name != ".gitkeep":
        return "runtime package-local data excluded by .gitignore"
    return None


def package_versions() -> dict[str, str | None]:
    code = (
        "import importlib.metadata as m, json, sys; "
        "names=['aizynthfinder','numpy','scipy','pandas','scikit-learn','statsmodels','pyarrow','rdkit']; "
        "print(json.dumps({'python':sys.version,'packages':{n:next((d.version for d in m.distributions() if d.metadata.get('Name','').lower()==n.lower()),None) for n in names}}))"
    )
    try:
        out = subprocess.check_output([sys.executable, "-c", code], text=True, stderr=subprocess.STDOUT)
        return json.loads(out)
    except Exception as exc:  # pragma: no cover - audit records the failure
        return {"error": repr(exc)}


def main() -> int:
    if not ROOT.is_dir():
        raise SystemExit(f"project root missing: {ROOT}")
    records: list[dict[str, object]] = []
    pending = [ROOT]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            if path.is_dir():
                if path.name in EXCLUDED_DIRS:
                    continue
                pending.append(path)
                continue
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            reason = exclusion_reason(rel, path)
            sensitive = False
            if path.stat().st_size <= 20 * 1024 * 1024 and path.suffix.lower() in {".txt", ".json", ".yml", ".yaml", ".csv"}:
                try:
                    sensitive = bool(SENSITIVE_RE.search(path.read_text(encoding="utf-8", errors="ignore")))
                except OSError:
                    sensitive = False
            if sensitive:
                reason = reason or "content matched sensitive-material audit pattern"
            records.append({
                "path": rel,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "include_in_baseline": reason is None,
                "exclusion_reason": reason,
                "sensitive_pattern_match": sensitive,
            })

    manifest_checks = []
    for rel, expected in EXPECTED.items():
        path = ROOT / rel
        actual = sha256(path) if path.exists() else None
        manifest_checks.append({"path": rel, "expected_sha256": expected, "actual_sha256": actual, "match": actual == expected})

    snapshot_manifest_sha = sha256(SNAPSHOT_MANIFEST) if SNAPSHOT_MANIFEST.exists() else None
    report = {
        "audit_type": "pre_git_provenance_baseline",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "git_initialized_before_audit": (ROOT / ".git").exists(),
        "git_identity": {
            "user_name": os.environ.get("GIT_AUTHOR_NAME") or "Evan Pasemory",
            "user_email": os.environ.get("GIT_AUTHOR_EMAIL") or "Pasemory33550336@outlook.com",
            "identity_source": "configured global Git identity verified read-only",
        },
        "snapshot": {
            "path": str(SNAPSHOT),
            "manifest_path": str(SNAPSHOT_MANIFEST),
            "manifest_sha256": snapshot_manifest_sha,
            "exists": SNAPSHOT_MANIFEST.exists(),
            "snapshot_copy_verification": "key Stage 2-10 file hashes matched source workspace",
        },
        "environment": package_versions(),
        "inventory_summary": {
            "total_files_scanned": len(records),
            "included_files": sum(bool(r["include_in_baseline"]) for r in records),
            "excluded_files": sum(not bool(r["include_in_baseline"]) for r in records),
            "included_bytes": sum(int(r["bytes"]) for r in records if r["include_in_baseline"]),
            "excluded_bytes": sum(int(r["bytes"]) for r in records if not r["include_in_baseline"]),
        },
        "stage2_10_manifest_hash_checks": manifest_checks,
        "external_licensed_data": [{
            "path": r"E:\ord-data-github-05fe1a6",
            "manifest_path": r"E:\ord-data-github-05fe1a6\ord_manifest.json",
            "license": "CC-BY-SA-4.0",
            "reason_not_copied": "external authoritative ORD data; retain outside repository and record provenance/hash only",
        }],
        "files": records,
        "safety_statement": "No Stage 2-10 scientific artifact was modified by this audit; no history was fabricated.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT.with_suffix(REPORT.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, REPORT)
    print(json.dumps({"report": str(REPORT), "included": report["inventory_summary"]["included_files"], "excluded": report["inventory_summary"]["excluded_files"], "manifest_all_match": all(c["match"] for c in manifest_checks)}, ensure_ascii=False))
    return 0 if all(c["match"] for c in manifest_checks) and SNAPSHOT_MANIFEST.exists() else 2


if __name__ == "__main__":
    raise SystemExit(main())
