"""Hashing and runtime provenance helpers for Stage 11 release audits."""
from __future__ import annotations

import hashlib
import importlib
import json
import platform
import sys
from pathlib import Path


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def runtime_versions() -> dict[str, str]:
    modules = {
        "numpy": "numpy", "pandas": "pandas", "pyarrow": "pyarrow",
        "sklearn": "sklearn", "scipy": "scipy", "statsmodels": "statsmodels",
        "aizynthfinder": "aizynthfinder", "rdkit": "rdkit",
    }
    result = {"python": platform.python_version(), "python_executable": sys.executable}
    for label, module_name in modules.items():
        try:
            module = importlib.import_module(module_name)
            result[label] = str(getattr(module, "__version__", "unknown"))
        except Exception as exc:
            result[label] = f"UNAVAILABLE:{type(exc).__name__}"
    return result


def canonical_content_hash(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() != ".json":
        return sha256(p)
    value = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        for key in ("created_at", "created_at_utc", "start_time_utc", "end_time_utc", "run_id"):
            value.pop(key, None)
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()
