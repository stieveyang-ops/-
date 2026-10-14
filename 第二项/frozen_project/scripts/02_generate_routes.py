from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "config_benchmark.yml"
TARGET_REPORT = ROOT / "reports" / "stage2_targets_validation.json"
REPORT = ROOT / "reports" / "stage2_route_generation.json"
SELECTED_POLICY = "uspto"
SELECTED_STOCK = "zinc"
TARGETS_SMI = ROOT / "data" / "generated" / "targets.smi"
ROUTES = ROOT / "data" / "generated" / "routes_raw.json"
LOG = ROOT / "reports" / "stage2_aizynthcli.log"


def main() -> int:
    result = {"stage": 2, "status": "FAIL", "errors": [], "warnings": [], "search_executed": False}
    try:
        stage1 = json.loads((ROOT / "reports" / "environment_check.json").read_text(encoding="utf-8"))
        if stage1.get("overall_status") != "PASS":
            result["status"] = "BLOCKED_STAGE1"
            result["errors"].append("Stage 1 environment report is not PASS")
        elif "filter" in yaml.safe_load(CONFIG.read_text(encoding="utf-8")):
            result["status"] = "BLOCKED_STAGE1_CONFIG"
            result["errors"].append("benchmark config contains filter section")
        elif json.loads(TARGET_REPORT.read_text(encoding="utf-8")).get("status") != "PASS":
            result["status"] = "BLOCKED_TARGET_VALIDATION"
            result["errors"].append("targets validation report is not PASS")
        else:
            cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
            policies = list((cfg.get("expansion") or {}).keys())
            stocks = list((cfg.get("stock") or {}).keys())
            result.update({"benchmark_config": "config/config_benchmark.yml", "benchmark_config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest().upper(), "expansion_policies_available": policies, "stocks_available": stocks, "nproc": 1, "filter_loaded_for_search": False})
            if SELECTED_POLICY not in policies:
                result["status"] = "BLOCKED_POLICY_NOT_FOUND"
                result["errors"].append(f"explicitly selected policy {SELECTED_POLICY!r} is not available: {policies}")
            elif SELECTED_STOCK not in stocks:
                result["status"] = "BLOCKED_STOCK_NOT_FOUND"
                result["errors"].append(f"explicitly selected stock {SELECTED_STOCK!r} is not available: {stocks}")
            elif len(stocks) != 1 and SELECTED_STOCK not in stocks:
                result["status"] = "BLOCKED_AMBIGUOUS_STOCK"
                result["errors"].append(f"benchmark exposes {len(stocks)} stocks; explicit research selection required")
            else:
                result.update({"expansion_policy_selected": SELECTED_POLICY, "stock_selected": SELECTED_STOCK})
                cmd = [sys.executable, "-m", "aizynthfinder.interfaces.aizynthcli", "--config", str(CONFIG), "--smiles", str(TARGETS_SMI), "--policy", SELECTED_POLICY, "--stocks", SELECTED_STOCK, "--output", str(ROUTES)]
                result["command"] = cmd
                with LOG.open("w", encoding="utf-8") as log:
                    proc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
                result["search_executed"] = True
                result["return_code"] = proc.returncode
                if proc.returncode != 0:
                    result["status"] = "BLOCKED_SEARCH_EXECUTION"
                    result["errors"].append(f"aizynthcli returned {proc.returncode}")
                elif not ROUTES.is_file():
                    result["status"] = "BLOCKED_OUTPUT_SCHEMA"
                    result["errors"].append("routes_raw.json was not created")
                else:
                    import pandas as pd
                    df = pd.read_json(ROUTES, orient="table")
                    target_report = json.loads(TARGET_REPORT.read_text(encoding="utf-8"))
                    if len(df) != target_report["target_count"] or not {"target", "trees"}.issubset(df.columns):
                        result["status"] = "BLOCKED_OUTPUT_SCHEMA"
                        result["errors"].append(f"output rows/columns invalid: rows={len(df)} cols={list(df.columns)}")
                    else:
                        result["status"] = "PASS"
                        result["target_count"] = len(df)
                        result["route_count_total"] = int(sum(len(x) for x in df["trees"]))
                        result["targets_without_routes"] = int(sum(len(x) == 0 for x in df["trees"]))
                        result["routes_raw_sha256"] = hashlib.sha256(ROUTES.read_bytes()).hexdigest().upper()
                        result["target_summary"] = [{"target": row.target, "number_of_routes": len(row.trees)} for row in df.itertuples()]
                result["next_human_action"] = None
    except Exception as exc:
        result["errors"].append(f"exception: {type(exc).__name__}: {exc}")
        result["status"] = "BLOCKED_PREFLIGHT"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
