from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "config" / "config_benchmark.yml"
PROD = ROOT / "config" / "config_production.yml"
REPORT = ROOT / "reports" / "config_validation.json"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def paths_from_config(cfg: dict) -> list[str]:
    out: list[str] = []
    for values in cfg.get("expansion", {}).values():
        out.extend(values if isinstance(values, list) else [values])
    for value in cfg.get("stock", {}).values():
        out.append(value if isinstance(value, str) else value.get("path", ""))
    for value in cfg.get("filter", {}).values():
        if isinstance(value, dict):
            out.append(value.get("model", ""))
        elif isinstance(value, str):
            out.append(value)
    return [p for p in out if p]


def main() -> int:
    result = {"stage": 1, "status": "FAIL", "checks": {}, "errors": []}
    try:
        b, p = load_yaml(BENCH), load_yaml(PROD)
        result["checks"]["benchmark_has_filter_section"] = "filter" in b
        result["checks"]["production_has_quick_filter"] = any(
            isinstance(v, str)
            or (isinstance(v, dict) and v.get("type", "quick-filter") == "quick-filter")
            for v in p.get("filter", {}).values()
        )
        p_core = deepcopy(p)
        p_core.pop("filter", None)
        core_keys = ["search", "expansion", "stock", "post_processing"]
        result["checks"]["non_filter_settings_equal"] = all(
            b.get(k) == p_core.get(k) for k in core_keys
        )
        refs = sorted(set(paths_from_config(b) + paths_from_config(p)))
        result["checks"]["referenced_files"] = {
            path: {"exists": os.path.isfile(path), "readable": os.access(path, os.R_OK)}
            for path in refs
        }
        missing = [x for x, v in result["checks"]["referenced_files"].items() if not all(v.values())]
        if "filter" in b:
            result["errors"].append("benchmark config contains filter section")
        if not result["checks"]["production_has_quick_filter"]:
            result["errors"].append("production config has no QuickFilter")
        if not result["checks"]["non_filter_settings_equal"]:
            result["errors"].append("non-filter settings differ")
        if missing:
            result["errors"].append(f"missing/unreadable references: {missing}")
        if not result["errors"]:
            from aizynthfinder.context.config import Configuration

            bc = Configuration.from_file(str(BENCH))
            pc = Configuration.from_file(str(PROD))
            result["checks"]["benchmark_filter_items"] = bc.filter_policy.items
            result["checks"]["benchmark_filter_selection"] = bc.filter_policy.selection
            result["checks"]["production_filter_items"] = pc.filter_policy.items
            result["checks"]["production_filter_loaded"] = bool(pc.filter_policy.items)
            if bc.filter_policy.items or bc.filter_policy.selection:
                result["errors"].append("benchmark loaded filter policy")
            if not pc.filter_policy.items:
                result["errors"].append("production QuickFilter not loaded")
    except Exception as exc:
        result["errors"].append(f"exception: {type(exc).__name__}: {exc}")
    result["status"] = "PASS" if not result["errors"] else "FAIL"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
