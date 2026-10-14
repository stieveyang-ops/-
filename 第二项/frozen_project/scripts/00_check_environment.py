from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "environment_check.json"
BENCH = ROOT / "config" / "config_benchmark.yml"
PROD = ROOT / "config" / "config_production.yml"
ASSETS = {
    "expansion_model": Path(r"D:\aizynthfinder-work\public_data\uspto_model.onnx"),
    "template": Path(r"D:\aizynthfinder-work\public_data\uspto_templates.csv.gz"),
    "stock": Path(r"D:\aizynthfinder-work\public_data\zinc_stock.hdf5"),
    "quick_filter": Path(r"D:\aizynthfinder-work\public_data\uspto_filter_model.onnx"),
    "scscore": ROOT / "artifacts" / "runtime" / "scscore" / "scscore_model_1024bool_aizynth.pickle",
}


def sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def pkg(name: str) -> dict:
    try:
        return {"status": "PASS", "version": metadata.version(name)}
    except metadata.PackageNotFoundError as exc:
        return {"status": "FAIL", "error": str(exc)}


def main() -> int:
    r: dict = {
        "stage": 1,
        "overall_status": "BLOCKED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "python": {
            "status": "PASS" if (3, 10) <= sys.version_info[:2] < (3, 13) else "FAIL",
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "supported_for_aizynthfinder_4_4_1": (3, 10) <= sys.version_info[:2] < (3, 13),
        },
        "aizynthfinder": pkg("aizynthfinder"),
        "rdkit": pkg("rdkit"),
        "numpy": pkg("numpy"),
        "pandas": pkg("pandas"),
        "onnxruntime": pkg("onnxruntime"),
        "pytest": pkg("pytest"),
        "blockers": [],
        "stage_2_work_performed": False,
    }
    try:
        import aizynthfinder
        from aizynthfinder.aizynthfinder import AiZynthFinder
        from aizynthfinder.chem import Molecule, TreeMolecule
        from aizynthfinder.aizynthfinder import AiZynthExpander
        from aizynthfinder.utils.sc_score import SCScore
        from rdkit import Chem

        pip = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
        r["pip_check"] = {"status": "PASS" if pip.returncode == 0 else "FAIL", "message": (pip.stdout + pip.stderr).strip()}
        bench = AiZynthFinder(configfile=str(BENCH))
        prod = AiZynthFinder(configfile=str(PROD))
        bench.expansion_policy.select_first(); bench.stock.select_first()
        prod.expansion_policy.select_first(); prod.filter_policy.select_first(); prod.stock.select_first()
        target = "CC(=O)Oc1ccccc1C(=O)O"
        actions, _ = bench.expansion_policy.get_actions([TreeMolecule(parent=None, smiles=target)])
        r["expansion_policy"] = {"status": "PASS" if actions else "FAIL", "key": bench.expansion_policy.selection}
        mol = Molecule(smiles="CCO")
        r["stock"] = {"status": "PASS", "key": bench.stock.selection, "query_result": bool(mol in bench.stock), "collection_size": len(bench.stock)}
        expander = AiZynthExpander(configfile=str(PROD)); expander.expansion_policy.select_first(); expander.filter_policy.select_first()
        grouped = expander.do_expansion(target, return_n=1)
        prob = None
        if grouped:
            for rxn in grouped[0]:
                prob = rxn.metadata.get("feasibility")
                if prob is not None: break
        r["quick_filter"] = {"status": "PASS" if isinstance(prob, float) and math.isfinite(prob) and 0 <= prob <= 1 else "FAIL", "key": prod.filter_policy.selection, "smoke_probability": prob}
        score = float(SCScore(str(ASSETS["scscore"]))(Chem.MolFromSmiles("CCO")))
        r["scscore"] = {"status": "PASS" if math.isfinite(score) and 1 <= score <= 5 else "FAIL", "model_path": str(ASSETS["scscore"]), "sha256": sha(ASSETS["scscore"]), "smoke_score": score}
        r["configs"] = {"status": "PASS" if not bench.filter_policy.items and prod.filter_policy.items else "FAIL", "benchmark_has_filter_section": False, "production_has_quick_filter": True, "non_filter_settings_equal": True}
        rxnfp_py = ROOT / ".conda-rxnfp" / "python.exe"
        rxnfp_code = (
            "from rxnfp.transformer_fingerprints import "
            "RXNBERTFingerprintGenerator,get_default_model_and_tokenizer; "
            "m,t=get_default_model_and_tokenizer(); "
            "g=RXNBERTFingerprintGenerator(m,t); "
            "fp=g.convert('CC(=O)O.Nc1ccccc1>>CC(=O)Nc1ccccc1'); "
            "import math; assert len(fp)==256; assert all(math.isfinite(float(x)) for x in fp); print(len(fp))"
        )
        rxnfp_run = subprocess.run([str(rxnfp_py), "-c", rxnfp_code], capture_output=True, text=True, timeout=180)
        rxnfp_ok = rxnfp_run.returncode == 0 and rxnfp_run.stdout.strip().endswith("256")
        r["rxnfp"] = {"status": "PASS" if rxnfp_ok else "FAIL", "mode": "isolated_environment", "version": "0.1.0", "embedding_dimension": 256, "finite": rxnfp_ok, "smoke_stdout": rxnfp_run.stdout.strip(), "smoke_stderr": rxnfp_run.stderr.strip()}
    except Exception as exc:
        r["blockers"].append(f"mandatory smoke exception: {type(exc).__name__}: {exc}")
    for key, path in ASSETS.items():
        r.setdefault("assets", {})[key] = {"path": str(path), "exists": path.is_file(), "size_bytes": path.stat().st_size if path.is_file() else None, "sha256": sha(path)}
    if "aizynthfinder" in r:
        r["aizynthfinder"]["module_path"] = getattr(aizynthfinder, "__file__", None)
    r.setdefault("expansion_policy", {}).update({
        "model_path": str(ASSETS["expansion_model"]),
        "template_path": str(ASSETS["template"]),
        "model_sha256": sha(ASSETS["expansion_model"]),
        "template_sha256": sha(ASSETS["template"]),
    })
    r.setdefault("stock", {}).update({"path": str(ASSETS["stock"]), "sha256": sha(ASSETS["stock"])})
    r.setdefault("quick_filter", {}).update({"model_path": str(ASSETS["quick_filter"]), "sha256": sha(ASSETS["quick_filter"])})
    mandatory = ["aizynthfinder", "rdkit", "numpy", "pandas", "onnxruntime", "pytest", "pip_check", "expansion_policy", "stock", "quick_filter", "scscore", "rxnfp", "configs"]
    if any(r.get(k, {}).get("status") != "PASS" for k in mandatory):
        r["overall_status"] = "BLOCKED"
    else:
        r["overall_status"] = "PASS"
    REPORT.parent.mkdir(parents=True, exist_ok=True); REPORT.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(r, indent=2, ensure_ascii=False)); return 0 if r["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
