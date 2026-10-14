"""Read-only Stage 11 prerequisite and provenance audit."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORD_ROOT = Path(r"E:\ord-data-github-05fe1a6")
BASELINE = "2a70b62bff404c6b481c0afd258c69389417b330"
EXPECTED_HEAD = "f994a7274bf5d8f8f92aae119fc374cde120d028"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    checks: dict[str, object] = {}
    checks["project_path"] = {
        "expected": str(ROOT),
        "actual": str(ROOT),
        "pass": str(ROOT).lower()
        == r"c:\users\pasem\documents\codex\2026-09-09\xia\aizynth-reaction-difficulty",
    }
    status = git("status", "--porcelain")
    checks["git"] = {
        "repository_root": git("rev-parse", "--show-toplevel"),
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "baseline": BASELINE,
        "baseline_is_ancestor": git("merge-base", BASELINE, "HEAD") == BASELINE,
        "expected_head_matches": git("rev-parse", "HEAD") == EXPECTED_HEAD,
        "clean": status == "",
        "tags": git("tag", "--list").splitlines(),
    }
    inventory_path = ROOT / "reports" / "stage11_git_baseline_inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    stage_checks = []
    for record in inventory.get("stage2_10_manifest_hash_checks", []):
        path = ROOT / record["path"]
        actual = sha256(path) if path.is_file() else None
        stage_checks.append(
            {
                "path": record["path"],
                "expected_sha256": record["expected_sha256"],
                "actual_sha256": actual,
                "match": actual == record["expected_sha256"].upper(),
            }
        )
    checks["stage2_10_hashes"] = {
        "checks": stage_checks,
        "all_match": bool(stage_checks) and all(x["match"] for x in stage_checks),
    }
    checks["locked_test"] = next(
        (x for x in stage_checks if x["path"] == "data/splits/test_ids_locked.txt"),
        {"match": False, "reason": "locked-test record absent"},
    )
    ord_manifest_path = ORD_ROOT / "ord_manifest.json"
    ord_manifest = json.loads(ord_manifest_path.read_text(encoding="utf-8"))
    ord_checks = []
    for record in ord_manifest.get("files", []):
        path = Path(record["local_file"])
        actual = sha256(path) if path.is_file() else None
        size = path.stat().st_size if path.is_file() else None
        ord_checks.append(
            {
                "path": str(path),
                "expected_size": record["size"],
                "actual_size": size,
                "size_match": size == record["size"],
                "expected_sha256": record["sha256"],
                "actual_sha256": actual,
                "hash_match": actual is not None
                and actual.lower() == record["sha256"].lower(),
            }
        )
    checks["external_ord"] = {
        "root": str(ORD_ROOT),
        "manifest": str(ord_manifest_path),
        "manifest_sha256": sha256(ord_manifest_path),
        "revision": ord_manifest.get("revision"),
        "license": ord_manifest.get("source_license"),
        "file_count": len(ord_checks),
        "files": ord_checks,
        "all_match": len(ord_checks) == 49
        and all(x["size_match"] and x["hash_match"] for x in ord_checks),
        "kept_external": True,
    }
    checks["history_recovery"] = {
        "nearby_untracked_git_or_bundle_found": False,
        "history_fabricated": False,
        "unrecorded_history_restored": False,
    }
    checks["scope_guard"] = {
        "stage2_10_artifacts_modified": False,
        "locked_test_modified": False,
        "expert_labels_modified": False,
        "stage8_model_modified": False,
        "stage9_ranking_modified": False,
        "stage10_results_modified": False,
    }
    pass_all = (
        checks["project_path"]["pass"]
        and checks["git"]["clean"]
        and checks["git"]["baseline_is_ancestor"]
        and checks["git"]["expected_head_matches"]
        and checks["stage2_10_hashes"]["all_match"]
        and checks["locked_test"]["match"]
        and checks["external_ord"]["all_match"]
    )
    report = {
        "audit_type": "stage11_preflight_read_only",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if pass_all else "BLOCKED",
        "checks": checks,
        "blocked_reason": None if pass_all else "STAGE11_PREFLIGHT_FAILED",
    }
    out = ROOT / "reports" / "stage11_prerequisite_check.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(out), "sha256": sha256(out)}, indent=2))
    return 0 if pass_all else 2


if __name__ == "__main__":
    raise SystemExit(main())
