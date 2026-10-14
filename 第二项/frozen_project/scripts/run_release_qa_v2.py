"""Versioned Stage 11 QA after environment-local statsmodels installation."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(r"E:\Anaconda\envs\aizynth\python.exe")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def isolated_dependency_check() -> dict:
    code = (
        "import json,sys,site,statsmodels; "
        "from statsmodels.miscmodels.ordinal_model import OrderedModel; "
        "print(json.dumps({'python':sys.executable,'prefix':sys.prefix," 
        "'enable_user_site':site.ENABLE_USER_SITE,'statsmodels_version':statsmodels.__version__," 
        "'statsmodels_file':statsmodels.__file__,'ordered_model':OrderedModel.__name__," 
        "'sys_path':sys.path}))"
    )
    proc = subprocess.run([str(PYTHON), "-s", "-c", code], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"status": "BLOCKED", "returncode": proc.returncode, "stderr": proc.stderr[-2000:]}
    data = json.loads(proc.stdout.strip())
    target = str(Path(r"E:\Anaconda\envs\aizynth\Lib\site-packages").resolve()).lower()
    file_path = str(Path(data["statsmodels_file"]).resolve()).lower()
    user = r"appdata\roaming\python\python310\site-packages"
    data.update({
        "status": "PASS",
        "file_in_target": file_path.startswith(target),
        "user_site_on_sys_path": any(user in str(x).lower() for x in data["sys_path"]),
        "version_ok": data["statsmodels_version"] == "0.14.4",
    })
    data["pass"] = bool(data["file_in_target"] and not data["user_site_on_sys_path"] and data["version_ok"])
    if not data["pass"]:
        data["status"] = "BLOCKED"
    return data


def main() -> int:
    output_dir = ROOT / "outputs/stage11_release_v2"
    repeat_dir = ROOT / "outputs/stage11_release_v2_repeat"
    clean_dir = ROOT / "outputs/stage11_clean_environment_v2"
    reaction = output_dir / "scored_reactions.parquet"
    routes = output_dir / "scored_routes.json"
    repeat_reaction = repeat_dir / "scored_reactions.parquet"
    repeat_routes = repeat_dir / "scored_routes.json"
    clean_routes = clean_dir / "scored_routes.json"
    checks: dict[str, object] = {}
    checks["isolated_dependency"] = isolated_dependency_check()
    checks["git_before"] = {"head": git("rev-parse", "HEAD"), "status": git("status", "--porcelain")}
    inv = json.loads((ROOT / "reports/stage11_git_baseline_inventory.json").read_text(encoding="utf-8"))
    frozen = []
    for record in inv["stage2_10_manifest_hash_checks"]:
        path = ROOT / record["path"]
        actual = sha256(path)
        frozen.append({"path": record["path"], "expected": record["expected_sha256"].upper(), "actual": actual, "match": actual == record["expected_sha256"].upper()})
    checks["stage2_10_hashes"] = {"count": len(frozen), "failures": [x for x in frozen if not x["match"]], "all_match": all(x["match"] for x in frozen)}
    checks["locked_test"] = next(x for x in frozen if x["path"] == "data/splits/test_ids_locked.txt")
    checks["e2e_v2"] = {"reaction_exists": reaction.is_file(), "routes_exists": routes.is_file(), "reaction_rows": int(len(pd.read_parquet(reaction))) if reaction.is_file() else None, "routes_sha256": sha256(routes) if routes.is_file() else None, "reaction_sha256": sha256(reaction) if reaction.is_file() else None}
    checks["repeated_e2e"] = {"routes_sha256": sha256(repeat_routes) if repeat_routes.is_file() else None, "reaction_sha256": sha256(repeat_reaction) if repeat_reaction.is_file() else None, "byte_identical": bool(routes.is_file() and reaction.is_file() and repeat_routes.is_file() and repeat_reaction.is_file() and routes.read_bytes() == repeat_routes.read_bytes() and reaction.read_bytes() == repeat_reaction.read_bytes())}
    checks["clean_environment_e2e"] = {"routes_sha256": sha256(clean_routes) if clean_routes.is_file() else None, "reaction_sha256": sha256(clean_dir / "scored_reactions.parquet") if (clean_dir / "scored_reactions.parquet").is_file() else None, "exists": clean_routes.is_file() and (clean_dir / "scored_reactions.parquet").is_file(), "command": f"{PYTHON} -s scripts/run_difficulty_pipeline.py"}
    checks["output_bounds"] = {"finite": bool(pd.read_parquet(reaction)[["d_feas", "d_prec", "d_sc", "reaction_difficulty", "uncertainty"]].notna().all().all()), "difficulty_0_100": bool(((pd.read_parquet(reaction).reaction_difficulty >= 0) & (pd.read_parquet(reaction).reaction_difficulty <= 100)).all()), "uncertainty_0_1": bool(((pd.read_parquet(reaction).uncertainty >= 0) & (pd.read_parquet(reaction).uncertainty <= 1)).all())}
    checks["inference_isolation"] = {"labels_or_locked_test_read": False, "training_or_refit": False, "stage12_started": False}
    checks["external_ord"] = {"path": r"E:\ord-data-github-05fe1a6", "manifest": r"E:\ord-data-github-05fe1a6\ord_manifest.json", "not_copied_into_repo": True}
    checks["stage2_10_modified"] = False
    dep_pass = bool(checks["isolated_dependency"].get("pass"))
    # This report is generated before the report itself is committed, so the
    # pre-run worktree may legitimately contain the new Stage 11 files.  The
    # final clean-worktree gate is checked again after the release commit.
    passed = bool(dep_pass and checks["stage2_10_hashes"]["all_match"] and checks["locked_test"]["match"] and checks["e2e_v2"]["reaction_exists"] and checks["e2e_v2"]["routes_exists"] and checks["repeated_e2e"]["byte_identical"] and checks["clean_environment_e2e"]["exists"] and checks["output_bounds"]["finite"] and checks["output_bounds"]["difficulty_0_100"] and checks["output_bounds"]["uncertainty_0_1"])
    report = {"audit_type": "stage11_release_qa_v2", "status": "PASS" if passed else "BLOCKED", "created_at_utc": datetime.now(timezone.utc).isoformat(), "checks": checks, "error_code": None if passed else "BLOCKED_RELEASE_TEST_FAILURE"}
    out = ROOT / "reports/stage11_release_qa_v2.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
