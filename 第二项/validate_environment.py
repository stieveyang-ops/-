#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_VERSIONS = {
    "python": "3.10",
    "aizynthfinder": "4.4.1",
    "rdkit": "2023.9.6",
    "numpy": "1.26.4",
    "pandas": "2.3.3",
    "pyarrow": "25.0.0",
    "scipy": "1.15.2",
    "statsmodels": "0.14.4",
    "onnxruntime": "1.23.2",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def version_of(package: str, module_name: str | None = None) -> str:
    try:
        return importlib.metadata.version(package)
    except Exception:
        module = importlib.import_module(module_name or package)
        return str(getattr(module, "__version__", "unknown"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()
    root = args.package_root.resolve()
    project = root / "frozen_project"
    report_path = root / "environment_validation.json"
    errors: list[str] = []
    user_site_hits = [
        entry for entry in sys.path
        if str(Path.home() / "AppData" / "Roaming" / "Python").lower() in entry.lower()
    ]
    if user_site_hits:
        errors.append(f"user-site path is active despite isolated launch: {user_site_hits}")
    versions: dict[str, str] = {"python": ".".join(map(str, sys.version_info[:3]))}
    packages = {
        "aizynthfinder": "aizynthfinder",
        "rdkit": "rdkit",
        "numpy": "numpy",
        "pandas": "pandas",
        "pyarrow": "pyarrow",
        "scipy": "scipy",
        "statsmodels": "statsmodels",
        "onnxruntime": "onnxruntime",
    }
    for package, module in packages.items():
        try:
            versions[package] = version_of(package, module)
        except Exception as exc:
            versions[package] = f"UNAVAILABLE:{type(exc).__name__}"
            errors.append(f"missing package: {package}: {exc}")
    if not versions["python"].startswith(REQUIRED_VERSIONS["python"] + "."):
        errors.append(f"Python must be {REQUIRED_VERSIONS['python']}.x; found {versions['python']}")
    for package, expected in REQUIRED_VERSIONS.items():
        if package == "python":
            continue
        if versions.get(package) != expected:
            errors.append(f"{package} must be {expected}; found {versions.get(package)}")
    try:
        from statsmodels.miscmodels.ordinal_model import OrderedModel  # noqa: F401
        ordered_model = "PASS"
    except Exception as exc:
        ordered_model = f"FAIL:{type(exc).__name__}:{exc}"
        errors.append("OrderedModel import failed")

    required = [
        project / "config" / "config_production.yml",
        project / "reports" / "environment_check.json",
        project / "reports" / "stage5_manifest.json",
        project / "reports" / "stage8_manifest.json",
        project / "artifacts" / "difficulty_model.pkl",
        project / "artifacts" / "reference_rxnfp.npy",
        project / "artifacts" / "reference_metadata.parquet",
        project / "artifacts" / "reference_nn_index.joblib",
        project / "artifacts" / "sc_delta_ecdf.npz",
        root / "external_public_data" / "public_data" / "uspto_model.onnx",
        root / "external_public_data" / "public_data" / "uspto_templates.csv.gz",
        root / "external_public_data" / "public_data" / "uspto_filter_model.onnx",
        root / "external_public_data" / "public_data" / "zinc_stock.hdf5",
        root / "package_reference_sha256.csv",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        errors.extend([f"missing required file: {path}" for path in missing])

    rxnfp_python = None
    for folder in (".conda-rxnfp-local", ".conda-rxnfp"):
        for candidate in (project / folder / "python.exe", project / folder / "Scripts" / "python.exe"):
            if candidate.is_file():
                rxnfp_python = candidate
                break
        if rxnfp_python is not None:
            break
    rxnfp_result: dict[str, object] = {"python": str(rxnfp_python) if rxnfp_python is not None else None, "status": "NOT_RUN"}
    if rxnfp_python is None:
        errors.append("RXNFP isolated runtime is missing; rebuild it using rebuild_rxnfp_environment.ps1")
        rxnfp_result["status"] = "FAIL_MISSING"
    else:
        try:
            # 用包内临时目录：部分安全策略会禁止 .conda-rxnfp 的解释器写入系统 TEMP
            # （实测 PermissionError: ...\Temp\portable_rxnfp_check_xxx\output.npy），
            # 而写交付包内部目录始终可用。改到包内后整机、受限环境均可通过校验。
            scratch_parent = root / "_runtime_check_tmp"
            try:
                scratch_parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                scratch_parent = None
            with tempfile.TemporaryDirectory(
                prefix="portable_rxnfp_check_",
                dir=str(scratch_parent) if scratch_parent is not None else None,
            ) as folder:
                inp = Path(folder) / "input.txt"
                out = Path(folder) / "output.npy"
                inp.write_text("CCO.O=C(O)c1ccccc1>>CCOC(=O)c1ccccc1", encoding="utf-8")
                proc = subprocess.run(
                    [str(rxnfp_python), str(project / "scripts" / "rxnfp_worker.py"), str(inp), str(out)],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )
                rxnfp_result.update({"returncode": proc.returncode, "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-2000:]})
                if proc.returncode != 0 or not out.is_file():
                    errors.append("RXNFP isolated runtime validation failed; rebuild it using rebuild_rxnfp_environment.ps1")
                    rxnfp_result["status"] = "FAIL"
                else:
                    import numpy as np
                    arr = np.load(out)
                    rxnfp_result.update({"status": "PASS" if arr.shape == (1, 256) else "FAIL_SHAPE", "shape": list(arr.shape), "finite": bool(np.isfinite(arr).all())})
                    if arr.shape != (1, 256) or not np.isfinite(arr).all():
                        errors.append(f"RXNFP returned invalid output shape/value: {arr.shape}")
        except Exception as exc:
            errors.append(f"RXNFP isolated runtime exception: {type(exc).__name__}: {exc}")
            rxnfp_result["status"] = "FAIL_EXCEPTION"
        finally:
            try:
                if scratch_parent is not None and scratch_parent.is_dir() and not any(scratch_parent.iterdir()):
                    scratch_parent.rmdir()
            except Exception:
                pass

    report = {
        "status": "PASS" if not errors else "BLOCKED",
        "package_root": str(root),
        "python_executable": str(Path(sys.executable).resolve()),
        "requested_python": str(args.python),
        "user_site_enabled": bool(__import__("site").ENABLE_USER_SITE),
        "user_site_paths_active": user_site_hits,
        "versions": versions,
        "required_versions": REQUIRED_VERSIONS,
        "ordered_model_import": ordered_model,
        "missing_files": missing,
        "rxnfp": rxnfp_result,
        "errors": errors,
        "scientific_artifacts_modified": False,
        "stage_1_11_recomputed": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
