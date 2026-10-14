"""Validate the target Stage 11 runtime without user-site packages."""
from __future__ import annotations

import hashlib
import json
import platform
import site
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET_PREFIX = Path(r"E:\Anaconda\envs\aizynth").resolve()
TARGET_SITE = (TARGET_PREFIX / "Lib" / "site-packages").resolve()
USER_SITE_FRAGMENT = r"AppData\Roaming\Python\Python310\site-packages".lower()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    result: dict[str, object] = {
        "audit_type": "stage11_dependency_validation_v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_python": sys.executable,
        "python_version": platform.python_version(),
        "sys_prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "sitepackages": [str(Path(x).resolve()) for x in site.getsitepackages()],
        "enable_user_site": site.ENABLE_USER_SITE,
        "sys_path": [str(x) for x in sys.path],
        "target_prefix": str(TARGET_PREFIX),
        "target_sitepackages": str(TARGET_SITE),
    }
    failures: list[str] = []
    if site.ENABLE_USER_SITE:
        failures.append("user_site_enabled")
    if Path(sys.prefix).resolve() != TARGET_PREFIX:
        failures.append("sys_prefix_mismatch")
    if any(USER_SITE_FRAGMENT in str(x).lower() for x in sys.path):
        failures.append("user_site_on_sys_path")
    try:
        import statsmodels
        from statsmodels.miscmodels.ordinal_model import OrderedModel

        stats_file = Path(statsmodels.__file__).resolve()
        result["statsmodels"] = {
            "version": str(statsmodels.__version__),
            "file": str(stats_file),
            "ordered_model_import": True,
            "file_under_target_sitepackages": TARGET_SITE in stats_file.parents,
            "file_sha256": sha256(stats_file),
            "ordered_model_name": OrderedModel.__name__,
        }
        if str(statsmodels.__version__) != "0.14.4":
            failures.append("statsmodels_version_mismatch")
        if TARGET_SITE not in stats_file.parents:
            failures.append("statsmodels_not_in_target_sitepackages")
    except Exception as exc:
        result["statsmodels"] = {
            "version": None,
            "file": None,
            "ordered_model_import": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        failures.append("ordered_model_import_failed")
    result["status"] = "PASS" if not failures else "BLOCKED"
    result["failures"] = failures
    result["user_site_dependency"] = bool(
        any(USER_SITE_FRAGMENT in str(x).lower() for x in sys.path)
    )
    out = ROOT / "reports" / "stage11_dependency_validation_v2.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log = ROOT / "reports" / "stage11_dependency_validation_v2.log"
    log.write_text(
        "STAGE 11 dependency validation v2\n"
        + json.dumps(result, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "report": str(out), "log": str(log), "failures": failures}, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
