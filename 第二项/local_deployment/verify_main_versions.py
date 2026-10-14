"""Check every target-machine requirement without changing frozen artifacts."""
import importlib.metadata
import json
import platform
import site
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
versions = {}
errors = []
for line in (root / "requirements-portable-main.txt").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    name, expected = line.split("==", 1)
    try:
        actual = platform.python_version() if name == "python" else importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        actual = "MISSING"
    versions[name] = {"expected": expected, "actual": actual, "match": actual == expected}
    if actual != expected:
        errors.append(f"{name}: expected {expected}, found {actual}")

from aizynthfinder.aizynthfinder import AiZynthFinder
from statsmodels.miscmodels.ordinal_model import OrderedModel
import tables
import onnxruntime
import tkinter

report = {
    "status": "PASS" if not errors else "BLOCKED",
    "python_executable": sys.executable,
    "user_site_enabled": site.ENABLE_USER_SITE,
    "versions": versions,
    "core_imports": "PASS",
    "errors": errors,
}
(root / "local_deployment" / "main_versions.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 2)
