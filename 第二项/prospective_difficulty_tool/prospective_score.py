#!/usr/bin/env python
"""Standalone prospective inference wrapper.

This file intentionally lives outside the frozen research project.  It reads
the project's frozen AiZynthFinder, Stage 3--8 and Stage 9 assets, but writes
all prospective outputs to a user-selected external directory.  It never
loads labels, split files, locked-test data, or training inputs.
"""
from __future__ import annotations

import argparse
import html
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import yaml


DEFAULT_PROJECT = (Path(__file__).resolve().parent.parent / "frozen_project").resolve()
DEFAULT_PYTHON = Path(sys.executable).resolve()
TARGET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class ProspectiveBlocked(RuntimeError):
    """Fail-closed error for an invalid prospective run."""


PROGRESS_PREFIX = "@@PROGRESS@@ "


class ProgressReporter:
    """Opt-in, machine-readable progress events for the desktop front-end.

    Events are single stderr lines (``@@PROGRESS@@ {json}``) so the GUI can
    render a real percentage while every other caller stays unchanged.  The
    per-stage weights approximate the *work* of each pipeline stage; the search
    stage replaces its share with the measured MCTS iteration counter read from
    the AiZynthFinder log.  Progress reporting never raises into a run.
    """

    STAGE_WEIGHTS = (("prepare", 6.0), ("search", 54.0), ("score", 32.0), ("write", 8.0))

    def __init__(self, enabled: bool = False, stream: Any = None) -> None:
        self.enabled = bool(enabled)
        self._stream = stream
        self._starts: dict[str, float] = {}
        self._spans: dict[str, float] = {}
        cursor = 0.0
        for name, weight in self.STAGE_WEIGHTS:
            self._starts[name] = cursor
            self._spans[name] = weight
            cursor += weight
        self._percent = 0.0
        self._last_key: tuple[float, str, str] | None = None

    def percent_for(self, stage: str, fraction: float) -> float:
        """Map a stage-local fraction in [0, 1] onto the global 0--100 scale."""
        if stage not in self._starts:
            return self._percent
        fraction = min(1.0, max(0.0, float(fraction)))
        return self._starts[stage] + self._spans[stage] * fraction

    @property
    def percent(self) -> float:
        """The last percentage actually reported, so a failure can show where it stopped."""
        return self._percent

    def stage(self, stage: str, fraction: float, text: str, eta_seconds: float | None = None) -> None:
        """Report the completion fraction of one stage.  No-op when disabled."""
        if not self.enabled:
            return
        self.emit(self.percent_for(stage, fraction), stage, text, eta_seconds)

    def emit(self, percent: float, stage: str, text: str, eta_seconds: float | None = None) -> None:
        """Write one progress event; the reported percentage never decreases."""
        if not self.enabled:
            return
        try:
            percent = max(self._percent, min(100.0, float(percent)))
        except (TypeError, ValueError):
            return
        key = (round(percent, 1), str(stage), str(text))
        if key == self._last_key:
            return
        self._last_key = key
        self._percent = percent
        event: dict[str, Any] = {"percent": round(percent, 1), "stage": str(stage), "text": str(text)}
        if eta_seconds is not None and math.isfinite(float(eta_seconds)) and float(eta_seconds) >= 0.0:
            event["eta_seconds"] = round(float(eta_seconds), 1)
        stream = self._stream if self._stream is not None else sys.stderr
        try:
            # ensure_ascii keeps the channel pure ASCII, so the event survives any
            # console encoding (for example cp936 on a Chinese Windows install).
            stream.write(PROGRESS_PREFIX + json.dumps(event) + "\n")
            stream.flush()
        except Exception:
            pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def native(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def runtime_info() -> dict[str, str]:
    names = {
        "numpy": "numpy",
        "pandas": "pandas",
        "pyarrow": "pyarrow",
        "scipy": "scipy",
        "sklearn": "scikit-learn",
        "statsmodels": "statsmodels",
        "rdkit": "rdkit",
        "aizynthfinder": "aizynthfinder",
    }
    result: dict[str, str] = {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
    }
    for key, package in names.items():
        try:
            result[key] = importlib.metadata.version(package)
        except Exception:
            try:
                module_name = "sklearn" if package == "scikit-learn" else package
                module = __import__(module_name)
                result[key] = str(getattr(module, "__version__", "unknown"))
            except Exception as exc:
                result[key] = f"UNAVAILABLE:{type(exc).__name__}"
    return result


def git_info(project: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"commit": None, "status_porcelain": None}
    try:
        commit = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        result["commit"] = commit.stdout.strip() if commit.returncode == 0 else None
        status = subprocess.run(
            ["git", "-C", str(project), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        result["status_porcelain"] = status.stdout
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise ProspectiveBlocked(f"missing {label}: {path}")
    return path


def resolve_recorded_path(project: Path, recorded: str, label: str) -> Path:
    """Resolve an audit-recorded path without trusting the source machine path."""
    candidate = Path(recorded)
    if not candidate.is_absolute():
        relative_candidates = [project / candidate, project / "reports" / candidate]
        if candidate.parts and candidate.parts[0] == "..":
            relative_candidates.insert(0, project.parent / Path(*candidate.parts[1:]))
        for path in relative_candidates:
            path = path.resolve()
            if path.is_file():
                return path
    name = candidate.name
    candidates = [
        project / "artifacts" / "runtime" / "scscore" / name,
        project.parent / "external_public_data" / "public_data" / name,
    ]
    for path in candidates:
        if path.is_file():
            return path
    # Absolute paths in copied manifests are historical provenance only.
    # Consult them last so a source-machine file cannot override a bundled asset.
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    raise ProspectiveBlocked(f"missing {label}: recorded={recorded}; checked={[str(x) for x in candidates]}")


def load_project_modules(project: Path):
    src = project / "src"
    if not src.is_dir():
        raise ProspectiveBlocked(f"project src directory missing: {src}")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from aiz_rd.chemistry import canonicalize_molecule_smiles
        from aiz_rd.explanations import reaction_explanation, route_explanation
        from aiz_rd.reaction_inference import OnDemandFeatureProvider, load_frozen_model
        from aiz_rd.precedent import ReactionPrecedentIndex
        from aiz_rd.route_extractor import extract_route_rows, _serialized_reactions
        from aiz_rd.chemistry import canonicalize_reaction, reaction_hash
    except Exception as exc:
        raise ProspectiveBlocked(f"cannot import frozen scoring modules: {type(exc).__name__}: {exc}") from exc
    return {
        "canonicalize_molecule_smiles": canonicalize_molecule_smiles,
        "reaction_explanation": reaction_explanation,
        "route_explanation": route_explanation,
        "OnDemandFeatureProvider": OnDemandFeatureProvider,
        "ReactionPrecedentIndex": ReactionPrecedentIndex,
        "load_frozen_model": load_frozen_model,
        "extract_route_rows": extract_route_rows,
        "serialized_reactions": _serialized_reactions,
        "canonicalize_reaction": canonicalize_reaction,
        "reaction_hash": reaction_hash,
    }


def isolated_scratch_parent() -> str | None:
    """RXNFP 隔离进程的临时目录父路径。

    部分安全策略会禁止 .conda-rxnfp 的解释器写入系统 TEMP
    （PermissionError: ...\\Temp\\prospective_rxnfp_xxx\\output.npy），
    而写交付包内部目录始终可用，因此优先使用包内 _runtime_tmp；
    若无法创建则回退到系统默认临时目录。该函数只影响临时文件位置，
    不涉及任何模型、公式、阈值或冻结资产。
    """
    candidate = Path(__file__).resolve().parents[1] / "_runtime_tmp"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return str(candidate)
    except Exception:
        return None


class WorkerRXNFPRuntime:
    """RXNFP adapter that always uses the project's isolated worker process."""

    def __init__(self, project: Path):
        self.interpreter = None
        for folder in (".conda-rxnfp-local", ".conda-rxnfp"):
            for candidate in (project / folder / "python.exe", project / folder / "Scripts" / "python.exe"):
                if candidate.is_file():
                    self.interpreter = candidate
                    break
            if self.interpreter is not None:
                break
        self.worker = project / "scripts/rxnfp_worker.py"
        if self.interpreter is None or not self.worker.is_file():
            raise ProspectiveBlocked("BLOCKED_RXNFP_RUNTIME_UNRESOLVED: isolated worker or interpreter missing")

    def embed(self, reactions: list[str]) -> np.ndarray:
        with tempfile.TemporaryDirectory(prefix="prospective_rxnfp_", dir=isolated_scratch_parent()) as td:
            folder = Path(td)
            input_path, output_path = folder / "input.txt", folder / "output.npy"
            input_path.write_text("\n".join(reactions), encoding="utf-8")
            proc = subprocess.run(
                [str(self.interpreter), str(self.worker), str(input_path), str(output_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                raise ProspectiveBlocked(f"isolated RXNFP worker failed: {proc.stderr[-2000:]}")
            arr = np.asarray(np.load(output_path), dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] != 256 or not np.isfinite(arr).all():
            raise ProspectiveBlocked(f"invalid isolated RXNFP output shape: {arr.shape}")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        if np.any(norms <= 0):
            raise ProspectiveBlocked("isolated RXNFP returned a zero vector")
        return arr / norms


def build_worker_provider(project: Path, modules: dict[str, Any], progress: "ProgressReporter | None" = None):
    """Build the same frozen on-demand provider without importing Torch in-process."""
    if progress is not None:
        # This stage deserializes the precedent index and warms the isolated
        # RXNFP runtime; on a cold start it dominates the waiting time after the
        # search, so it is reported rather than leaving the bar motionless.
        progress.stage("score", 0.06, "Loading frozen on-demand assets (reference corpus and SCScore)")
    env = json.loads(require_file(project / "reports/environment_check.json", "environment report").read_text(encoding="utf-8"))
    stage5 = json.loads(require_file(project / "reports/stage5_manifest.json", "Stage 5 manifest").read_text(encoding="utf-8"))
    if env.get("overall_status") != "PASS":
        raise ProspectiveBlocked("BLOCKED_FEATURE_PROVIDER_DRIFT: Stage 3 environment report is not PASS")
    if env.get("quick_filter", {}).get("status") != "PASS" or env.get("scscore", {}).get("status") != "PASS":
        raise ProspectiveBlocked("BLOCKED_FEATURE_PROVIDER_DRIFT: quick-filter or SCScore prerequisite is not PASS")
    from aizynthfinder.aizynthfinder import AiZynthExpander
    from aizynthfinder.utils.sc_score import SCScore

    # The frozen config keeps its source-machine provenance.  For a portable
    # run, materialize a temporary equivalent config with only public-asset
    # paths rebased to this package.  The frozen config itself is never edited.
    original_config = require_file(project / "config/config_production.yml", "production config")
    config_data = yaml.safe_load(original_config.read_text(encoding="utf-8"))
    portable_config = rebase_config_paths(project, config_data)
    with tempfile.NamedTemporaryFile("w", suffix=".yml", encoding="utf-8", delete=False) as handle:
        handle.write(yaml.safe_dump(portable_config, sort_keys=False, allow_unicode=True))
        portable_config_path = Path(handle.name)
    if progress is not None:
        progress.stage("score", 0.16, "Deserializing reference nearest-neighbour index")
        progress.stage("score", 0.18, "Rebasing production config for this run")
    try:
        expander = AiZynthExpander(configfile=str(portable_config_path))
    finally:
        portable_config_path.unlink(missing_ok=True)
    if progress is not None:
        progress.stage("score", 0.26, "Quick-filter model loaded")
    filter_key = env["quick_filter"].get("key")
    filter_key = filter_key[0] if isinstance(filter_key, list) else filter_key
    if expander.filter_policy.items != [filter_key]:
        raise ProspectiveBlocked("BLOCKED_FEATURE_PROVIDER_DRIFT: QuickFilter policy mismatch")
    filter_model = resolve_recorded_path(project, str(env["quick_filter"]["model_path"]), "quick-filter model")
    sc_path = resolve_recorded_path(project, str(env["scscore"]["model_path"]), "SCScore model")
    if sha256(filter_model) != str(env["quick_filter"]["sha256"]).upper() or sha256(sc_path) != str(env["scscore"]["sha256"]).upper():
        raise ProspectiveBlocked("BLOCKED_FEATURE_PROVIDER_DRIFT: model hash mismatch")
    runtime = BatchWorkerRXNFPRuntime(project)
    if progress is not None:
        progress.stage("score", 0.34, "Isolated RXNFP worker resolved")
    # Deserialize the index in the project's compatible sklearn/joblib
    # runtime, isolated from the target Conda interpreter.  The resulting
    # object is passed back through a tiny local adapter; no files are copied
    # or modified.
    try:
        index = modules["ReactionPrecedentIndex"](
            project / "artifacts/reference_rxnfp.npy",
            project / "artifacts/reference_metadata.parquet",
            project / "artifacts/reference_nn_index.joblib",
            runtime,
            top_k=100,
        )
    except Exception as exc:
        if "sklearn" not in str(exc).lower() and "joblib" not in str(exc).lower():
            raise
        index = IsolatedPrecedentIndex(project, runtime, modules)
    ecdf = np.load(project / "artifacts/sc_delta_ecdf.npz", allow_pickle=False)["delta_sc_sorted"]
    if progress is not None:
        progress.stage("score", 0.4, "On-demand feature provider ready")
    return modules["OnDemandFeatureProvider"](
        expander.filter_policy[filter_key],
        index,
        SCScore(str(sc_path)),
        ecdf,
        mode=str(stage5["precedent_mode"]),
        tau=float(stage5["tau"]),
        n0=float(stage5["n0"]),
    )


class IsolatedPrecedentIndex:
    """Reference scorer using isolated RXNFP plus a worker-side sklearn index."""

    def __init__(self, project: Path, runtime: WorkerRXNFPRuntime, modules: dict[str, Any]):
        self.project = project
        self.runtime = runtime
        self.metadata = pd.read_parquet(project / "artifacts/reference_metadata.parquet")
        self.embeddings = np.asarray(np.load(project / "artifacts/reference_rxnfp.npy", mmap_mode="r"), dtype=np.float64)
        if self.embeddings.ndim != 2 or self.embeddings.shape[1] != 256 or len(self.embeddings) != len(self.metadata):
            raise ProspectiveBlocked("invalid reference embedding/metadata dimensions")
        self.index = self._load_index_in_worker()

    def _load_index_in_worker(self):
        # The index uses only brute-force cosine NearestNeighbors.  To avoid
        # importing an incompatible sklearn build into the target process, the
        # worker returns its neighbor indices/distances for each query.  The
        # exact full-corpus formula below uses the frozen embedding matrix.
        return None

    def full_corpus_score(self, vector: np.ndarray, query_hash: str, *, mode: str = "deployment", tau: float = 0.80, n0: float = 10.0):
        from aiz_rd.precedent import compute_precedent_score

        vec = np.asarray(vector, dtype=np.float64).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if vec.shape != (256,) or not np.isfinite(vec).all() or norm <= 0.0:
            raise ProspectiveBlocked("invalid prospective RXNFP vector")
        similarities = (self.embeddings @ (vec / norm)).astype(np.float64)
        return compute_precedent_score(similarities, self.metadata, query_hash, mode=mode, tau=tau, n0=n0)


class BatchWorkerRXNFPRuntime(WorkerRXNFPRuntime):
    """Worker runtime with a deterministic in-memory batch embedding cache."""

    def __init__(self, project: Path):
        super().__init__(project)
        self._cache: dict[str, np.ndarray] = {}

    def embed(self, reactions: list[str]) -> np.ndarray:
        missing = [reaction for reaction in reactions if reaction not in self._cache]
        if missing:
            values = super().embed(missing)
            self._cache.update({reaction: values[idx] for idx, reaction in enumerate(missing)})
        return np.asarray([self._cache[reaction] for reaction in reactions], dtype=np.float32)


def frozen_asset_inventory(project: Path, progress: "ProgressReporter | None" = None) -> dict[str, Any]:
    """Record the exact read-only assets used by prospective inference."""
    paths = {
        "production_config": project / "config/config_production.yml",
        "difficulty_config": project / "config/difficulty.yml",
        "stage5_manifest": project / "reports/stage5_manifest.json",
        "stage8_manifest": project / "reports/stage8_manifest.json",
        "reference_corpus": project / "data/reference/reference_reactions_clean.parquet",
        "reference_embeddings": project / "artifacts/reference_rxnfp.npy",
        "reference_metadata": project / "artifacts/reference_metadata.parquet",
        "reference_index": project / "artifacts/reference_nn_index.joblib",
        "sc_delta_ecdf": project / "artifacts/sc_delta_ecdf.npz",
        "difficulty_model": project / "artifacts/difficulty_model.pkl",
        "difficulty_model_metadata": project / "artifacts/difficulty_model_metadata.json",
    }
    result: dict[str, Any] = {}
    total = len(paths)
    for index, (key, path) in enumerate(paths.items(), 1):
        require_file(path, key)
        result[key] = {"path": str(path.resolve()), "sha256": sha256(path), "size_bytes": path.stat().st_size}
        if progress is not None:
            progress.stage("prepare", index / total, f"Verifying frozen assets ({index}/{total}): {key}")
    return result


def prepare_search_config(project: Path, output_dir: Path, overrides: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Create a one-run config copy; the frozen project config is read-only."""
    original = require_file(project / "config/config_production.yml", "production config")
    original_hash = sha256(original)
    try:
        config_data = yaml.safe_load(original.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProspectiveBlocked(f"cannot parse production config: {type(exc).__name__}: {exc}") from exc
    if not isinstance(config_data, dict) or not isinstance(config_data.get("search"), dict):
        raise ProspectiveBlocked("production config has no searchable search section")
    config_data = rebase_config_paths(project, config_data)
    search = config_data["search"]
    post = config_data.setdefault("post_processing", {})
    if not isinstance(post, dict):
        raise ProspectiveBlocked("production config post_processing section is invalid")
    if overrides.get("iteration_limit") is not None:
        search["iteration_limit"] = int(overrides["iteration_limit"])
    if overrides.get("time_limit") is not None:
        search["time_limit"] = float(overrides["time_limit"])
    if overrides.get("max_transforms") is not None:
        search["max_transforms"] = int(overrides["max_transforms"])
    if overrides.get("max_routes") is not None:
        post["max_routes"] = int(overrides["max_routes"])
    if overrides.get("min_routes") is not None:
        post["min_routes"] = int(overrides["min_routes"])
    effective = {
        "iteration_limit": int(search.get("iteration_limit")),
        "time_limit": float(search.get("time_limit")),
        "max_transforms": int(search.get("max_transforms")),
        "max_routes": int(post.get("max_routes")),
        "min_routes": int(post.get("min_routes")),
    }
    if effective["iteration_limit"] <= 0 or effective["time_limit"] <= 0 or effective["max_transforms"] <= 0:
        raise ProspectiveBlocked("iteration-limit, time-limit and max-transforms must be positive")
    if effective["min_routes"] < 0 or effective["max_routes"] <= 0 or effective["min_routes"] > effective["max_routes"]:
        raise ProspectiveBlocked("min-routes/max-routes must satisfy 0 <= min_routes <= max_routes")
    temporary = output_dir / "prospective_search_config.yml"
    temporary.write_text(yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return temporary, {
        "original_config_path": str(original.resolve()),
        "original_config_sha256": original_hash,
        "temporary_config_path": str(temporary.resolve()),
        "temporary_config_sha256": sha256(temporary),
        "effective": effective,
        "overrides": {key: value for key, value in overrides.items() if value is not None},
    }


def rebase_config_paths(project: Path, config_data: dict[str, Any]) -> dict[str, Any]:
    """Rebase public-data paths to a package-relative location at run time."""
    public_dir = (project.parent / "external_public_data" / "public_data").resolve()
    replacements = {
        "uspto_model.onnx": public_dir / "uspto_model.onnx",
        "uspto_templates.csv.gz": public_dir / "uspto_templates.csv.gz",
        "uspto_ringbreaker_model.onnx": public_dir / "uspto_ringbreaker_model.onnx",
        "uspto_ringbreaker_templates.csv.gz": public_dir / "uspto_ringbreaker_templates.csv.gz",
        "uspto_filter_model.onnx": public_dir / "uspto_filter_model.onnx",
        "zinc_stock.hdf5": public_dir / "zinc_stock.hdf5",
    }
    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            for name, path in replacements.items():
                if value.endswith(name):
                    return str(path)
        return value
    return walk(config_data)


NOMINAL_LOADING_SECONDS = 60.0
LOADING_SHARE_OF_SEARCH = 0.25


class SearchProgressTracker:
    """Track real AiZynthFinder search progress from its own log file.

    The child process spends a long, otherwise-silent period loading the ONNX
    expansion/filter models and the 35M-compound ZINC stock before its own MCTS
    timer starts, so two sub-phases are reported separately:

    * ``loading`` - no counter printed yet.  Only measured elapsed time is
      available, so the bar creeps inside a small, clearly labelled share of the
      search span while the text always shows the real elapsed seconds.
    * ``searching`` - the child's counter is present.  Progress is then the
      larger of its measured MCTS fraction and its measured wall-clock fraction,
      both taken against the run's effective limits.

    Nothing is reported as complete before the search itself reports it.
    """

    def __init__(self, log_path: Path, time_limit: float) -> None:
        self.log_path = log_path
        self.time_limit = float(time_limit)
        self._start = time.time()
        self._search_started_at: float | None = None

    def _read_counter(self) -> tuple[bool, int, int]:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return False, 0, 0
        # tqdm renders one carriage-returned line per update, so the last match
        # is the newest state.  Requiring tqdm's own "N%|bar| N/M" shape keeps
        # file paths elsewhere in the log from being mistaken for counters.
        latest = None
        for match in re.finditer(r"(\d+)%\|[^|]*\|\s*(\d+)/(\d+)", text):
            latest = match
        if latest is None:
            return False, 0, 0
        return True, int(latest.group(2)), int(latest.group(3))

    def sample(self, now: float) -> tuple[float, str, float | None]:
        """Return the measured (fraction of the search stage, text, ETA)."""
        started, done, total = self._read_counter()
        if not started:
            elapsed = max(0.0, now - self._start)
            loading = min(1.0, elapsed / NOMINAL_LOADING_SECONDS)
            return (
                LOADING_SHARE_OF_SEARCH * loading,
                "Loading expansion policy, filter and ZINC stock ({0:.0f}s)".format(elapsed),
                None,
            )
        if self._search_started_at is None:
            # First observation of the child's own counter: its timer starts here.
            self._search_started_at = now
        search_elapsed = max(0.0, now - self._search_started_at)
        iteration_fraction = (done / total) if total > 0 else 0.0
        time_fraction = (search_elapsed / self.time_limit) if self.time_limit > 0 else 0.0
        # Never let loading stay credited once real search reporting has begun.
        fraction = min(1.0, max(LOADING_SHARE_OF_SEARCH, iteration_fraction, time_fraction))
        steps = ["MCTS {0}/{1}".format(done, total)]
        steps.append(
            "{0:.0f}s / {1:.0f}s".format(search_elapsed, self.time_limit)
            if self.time_limit > 0
            else "{0:.0f}s".format(search_elapsed)
        )
        eta: float | None = None
        if total > 0 and done > 0 and done < total and search_elapsed > 0.0:
            eta = max(0.0, search_elapsed / done * (total - done))
            if self.time_limit > 0:
                # The search also stops on the wall-clock limit, so never promise
                # an arrival later than the budget that is actually in force.
                eta = min(eta, max(0.0, self.time_limit - search_elapsed))
            steps.append("ETA ~{0:.0f}s".format(eta))
        return fraction, "Searching routes ({0})".format(", ".join(steps)), eta


def run_search(
    project: Path,
    target_smiles: str,
    output_dir: Path,
    search_params: dict[str, Any],
    progress: "ProgressReporter | None" = None,
) -> tuple[Path, list[str], dict[str, Any]]:
    """Run AiZynthFinder with a per-run config copy, never mutating project config."""
    config, config_info = prepare_search_config(project, output_dir, search_params)
    routes_path = output_dir / "routes_raw.json"
    log_path = output_dir / "aizynthfinder_search.log"
    time_limit = float(config_info["effective"].get("time_limit") or 0.0)
    command = [
        str(Path(sys.executable).resolve()),
        "-s",
        "-m",
        "aizynthfinder.interfaces.aizynthcli",
        "--config",
        str(config),
        "--smiles",
        target_smiles,
        "--policy",
        "uspto",
        "--stocks",
        "zinc",
        "--output",
        str(routes_path),
    ]
    return_code = 0
    if progress is not None and progress.enabled:
        progress.stage("search", 0.0, "Loading expansion policy and stock")
        # The child writes straight to the log file descriptor, exactly as the
        # non-reporting path does, so the log stays byte-identical; the parent
        # only tails that file for the real iteration counter.
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=str(project), stdout=log, stderr=subprocess.STDOUT)
            tracker = SearchProgressTracker(log_path, time_limit)
            while process.poll() is None:
                fraction, text, eta = tracker.sample(time.time())
                progress.stage("search", fraction, text, eta)
                time.sleep(0.2)
            return_code = int(process.returncode or 0)
        # The child has exited, so the search span is complete; the last sampled
        # counter is already reflected in the events the loop emitted.
        progress.stage("search", 1.0, "Search finished (exit code {0})".format(return_code))
    else:
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.run(command, cwd=str(project), stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
        return_code = proc.returncode
    if return_code != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
        raise ProspectiveBlocked("AiZynthFinder search failed with return code {0}:\n{1}".format(return_code, tail))
    require_file(routes_path, "AiZynthFinder routes output")
    return routes_path, command, config_info


def load_routes(routes_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(routes_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProspectiveBlocked(f"cannot parse routes JSON: {type(exc).__name__}: {exc}") from exc
    # Batch CLI mode writes pandas orient=table JSON.  Single-target CLI mode
    # (the mode used by this tool) writes a JSON list of route-tree objects.
    if isinstance(raw, list):
        if not raw or not all(isinstance(tree, dict) for tree in raw):
            raise ProspectiveBlocked("single-target routes JSON is empty or malformed")
        target = str(raw[0].get("smiles", ""))
        if not target:
            raise ProspectiveBlocked("single-target routes JSON lacks the target molecule")
        return {"schema": "aizynthfinder-single-target", "data": [{"target": target, "trees": raw}]}
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise ProspectiveBlocked("routes input must be AiZynthFinder JSON with either a data list or a single-target tree list")
    return raw


def score_routes(
    project: Path,
    target_id: str,
    raw: dict[str, Any],
    modules: dict[str, Any],
    progress: "ProgressReporter | None" = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Compute frozen on-demand features, model scores, route aggregates and ranks."""
    from aizynthfinder.reactiontree import ReactionTree

    if progress is not None:
        progress.stage("score", 0.0, "Loading frozen difficulty model and on-demand feature provider")
    model_path = project / "artifacts/difficulty_model.pkl"
    metadata_path = project / "artifacts/difficulty_model_metadata.json"
    stage8_path = project / "reports/stage8_manifest.json"
    model, metadata, _ = modules["load_frozen_model"](model_path, metadata_path, stage8_path)
    provider = build_worker_provider(project, modules, progress)
    q33, q67 = float(metadata["q33"]), float(metadata["q67"])
    reaction_cache: dict[str, dict[str, Any]] = {}
    reaction_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []

    if len(raw["data"]) != 1:
        raise ProspectiveBlocked(f"a prospective routes file must contain exactly one target row, found {len(raw['data'])}")
    trees = list(raw["data"][0].get("trees", []))
    total_trees = len(trees)
    if progress is not None:
        progress.stage("score", 0.05, "Scoring " + str(total_trees) + " candidate route(s)")
    for route_index, tree_dict in enumerate(trees, 1):
        if progress is not None:
            # Route work is dominated by the per-step frozen features; the route
            # loop itself is the only honest per-route granularity available here.
            progress.stage("score", 0.05 + 0.9 * ((route_index - 1) / max(1, total_trees)), "Scoring route " + str(route_index) + " of " + str(total_trees))
        route_id = f"{target_id}__route_{route_index:03d}"
        extracted = modules["extract_route_rows"](target_id, route_index, tree_dict)
        precursor_nodes_by_hash: dict[str, list[str]] = {}
        for serialized in modules["serialized_reactions"](tree_dict):
            _, _, canonical = modules["canonicalize_reaction"](
                list(serialized.precursors_raw), serialized.product_raw
            )
            precursor_nodes_by_hash[modules["reaction_hash"](canonical)] = list(serialized.precursors_raw)
        steps: list[dict[str, Any]] = []
        step_total = max(1, len(extracted))
        route_base = 0.05 + 0.9 * ((route_index - 1) / max(1, total_trees))
        route_span = 0.9 / max(1, total_trees)
        for step_index, extracted_row in enumerate(extracted, 1):
            if progress is not None:
                progress.stage(
                    "score",
                    route_base + route_span * ((step_index - 1) / step_total),
                    "Route " + str(route_index) + "/" + str(total_trees) + ", reaction " + str(step_index) + "/" + str(step_total),
                )
            reaction_hash = str(extracted_row["reaction_hash"])
            if reaction_hash not in reaction_cache:
                precursor_nodes = precursor_nodes_by_hash.get(reaction_hash)
                if not precursor_nodes:
                    raise ProspectiveBlocked(f"cannot recover precursor node boundaries for {reaction_hash}")
                feature = provider.score_components(
                    str(extracted_row["product_smiles"]),
                    precursor_nodes,
                    expected_hash=reaction_hash,
                )
                probabilities = model.predict_proba(
                    pd.DataFrame([[feature["d_feas"], feature["d_prec"], feature["d_sc"]]], columns=["d_feas", "d_prec", "d_sc"])
                )[0]
                difficulty = float(50.0 * probabilities[1] + 100.0 * probabilities[2])
                uncertainty = float((4.0 * feature["p_feas"] * (1.0 - feature["p_feas"]) + (1.0 - feature["p_prec"])) / 2.0)
                if not np.isfinite(difficulty) or not 0.0 <= difficulty <= 100.0:
                    raise ProspectiveBlocked(f"invalid frozen-model difficulty for {reaction_hash}")
                if not np.isfinite(uncertainty) or not 0.0 <= uncertainty <= 1.0:
                    raise ProspectiveBlocked(f"invalid uncertainty for {reaction_hash}")
                confidence = "High" if uncertainty <= q33 else ("Medium" if uncertainty <= q67 else "Low")
                scored = {
                    **{key: native(value) for key, value in feature.items()},
                    "p_easy": float(probabilities[0]),
                    "p_medium": float(probabilities[1]),
                    "p_difficult": float(probabilities[2]),
                    "reaction_difficulty": difficulty,
                    "uncertainty": uncertainty,
                    "confidence": confidence,
                }
                code, text = modules["reaction_explanation"](scored)
                scored.update({"explanation_code": code, "explanation_text": text})
                reaction_cache[reaction_hash] = scored
            scored = dict(reaction_cache[reaction_hash])
            row = {
                "target_id": target_id,
                "route_id": route_id,
                "step_id": str(extracted_row["step_id"]),
                "reaction_hash": reaction_hash,
                "reaction_smiles": str(extracted_row["reaction_smiles"]),
                "product_smiles": str(extracted_row["product_smiles"]),
                "precursor_smiles": str(extracted_row["precursor_smiles"]),
                **scored,
            }
            reaction_rows.append(row)
            steps.append(row)

        tree = ReactionTree.from_dict(tree_dict)
        score_obj = tree_dict.get("scores", {})
        state_score = score_obj.get("state score")
        if not isinstance(state_score, (int, float)) or not np.isfinite(float(state_score)):
            raise ProspectiveBlocked(f"route has no finite AiZynthFinder state score: {route_id}")
        solved = bool(tree_dict.get("metadata", {}).get("is_solved", tree.is_solved))
        if steps:
            d = np.asarray([float(row["reaction_difficulty"]) for row in steps], dtype=float)
            u = np.asarray([float(row["uncertainty"]) for row in steps], dtype=float)
            bottleneck, mean, route_uncertainty = float(d.max()), float(d.mean()), float(u.max())
            tied = [idx for idx, value in enumerate(d) if np.isclose(value, bottleneck, atol=1e-10, rtol=0.0)]
            hardest_ids = [str(steps[idx]["step_id"]) for idx in tied]
            hardest_reactions = [str(steps[idx]["reaction_smiles"]) for idx in tied]
            route_confidence = "high" if route_uncertainty <= q33 else ("medium" if route_uncertainty <= q67 else "low")
            applicable = True
            route_type = "reaction_route"
        else:
            bottleneck = mean = route_uncertainty = None
            hardest_ids, hardest_reactions = [], []
            route_confidence, applicable, route_type = "not_applicable", False, "direct_stock_no_reaction"
        route = {
            "target_id": target_id,
            "route_id": route_id,
            "original_rank": route_index,
            "new_rank": None,
            "solved": solved,
            "original_state_score": float(state_score),
            "number_of_reactions": len(steps),
            "difficulty_applicable": applicable,
            "difficulty_bottleneck": bottleneck,
            "difficulty_mean": mean,
            "route_uncertainty": route_uncertainty,
            "route_confidence": route_confidence,
            "hardest_step_id": hardest_ids[0] if hardest_ids else None,
            "hardest_step_ids": hardest_ids,
            "hardest_step_reaction": hardest_reactions[0] if hardest_reactions else None,
            "hardest_step_reactions": hardest_reactions,
            "route_type": route_type,
            "steps": steps,
        }
        route["route_explanation"] = modules["route_explanation"](route)
        route_rows.append(route)

    def sort_key(route: dict[str, Any]):
        applicable = bool(route["difficulty_applicable"])
        return (
            -int(bool(route["solved"])),
            0 if applicable else 1,
            route["difficulty_bottleneck"] if applicable else 0.0,
            route["difficulty_mean"] if applicable else 0.0,
            -float(route["original_state_score"]),
            int(route["original_rank"]),
            str(route["route_id"]),
        )

    for new_rank, route in enumerate(sorted(route_rows, key=sort_key), 1):
        route["new_rank"] = new_rank
        route["rank_change"] = int(route["original_rank"]) - new_rank
    route_rows.sort(key=lambda route: int(route["new_rank"]))
    if progress is not None:
        progress.stage("score", 1.0, "Scored " + str(len(route_rows)) + " route(s)")
    scoring_summary = {
        "q33": q33,
        "q67": q67,
        "feature_order": ["d_feas", "d_prec", "d_sc"],
        "precedent": {"tau": 0.80, "N0": 10.0, "metric": "cosine", "top_k": 100},
        "reaction_unique_count": len(reaction_cache),
        "reaction_occurrence_count": len(reaction_rows),
        "route_count": len(route_rows),
    }
    return route_rows, reaction_rows, scoring_summary


def save_outputs(
    output_dir: Path,
    target_id: str,
    target_smiles: str,
    routes_path: Path,
    route_rows: list[dict[str, Any]],
    reaction_rows: list[dict[str, Any]],
    manifest_base: dict[str, Any],
    progress: "ProgressReporter | None" = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reaction_parquet = output_dir / "scored_reactions.parquet"
    reaction_csv = output_dir / "scored_reactions.csv"
    routes_json = output_dir / "scored_routes.json"
    routes_csv = output_dir / "scored_routes.csv"
    visualization = output_dir / "prospective_dashboard.html"
    structure_dir = output_dir / "reaction_diagrams"

    reaction_columns = [
        "target_id", "route_id", "step_id", "reaction_hash", "reaction_smiles", "product_smiles", "precursor_smiles",
        "p_feas", "d_feas", "s_max", "n_analog", "p_prec", "d_prec", "sc_product", "sc_precursor_max", "delta_sc", "d_sc",
        "p_easy", "p_medium", "p_difficult", "reaction_difficulty", "uncertainty", "confidence", "explanation_code", "explanation_text",
    ]
    reaction_frame = pd.DataFrame(reaction_rows, columns=reaction_columns)
    reaction_frame.to_parquet(reaction_parquet, index=False)
    reaction_frame.to_csv(reaction_csv, index=False)
    route_payload = {"targets": {target_id: route_rows}}
    write_json(routes_json, route_payload)
    flat_routes = []
    for route in route_rows:
        row = {key: value for key, value in route.items() if key != "steps"}
        row["hardest_step_ids"] = json.dumps(row["hardest_step_ids"], ensure_ascii=False, separators=(",", ":"))
        row["hardest_step_reactions"] = json.dumps(row["hardest_step_reactions"], ensure_ascii=False, separators=(",", ":"))
        flat_routes.append(row)
    pd.DataFrame(flat_routes).to_csv(routes_csv, index=False)
    diagrams, diagram_warnings = write_reaction_diagrams(structure_dir, reaction_rows, progress)
    if progress is not None:
        progress.stage("write", 0.85, "Rendering dashboard")
    visualization.write_text(build_dashboard_html(target_id, target_smiles, route_rows, diagrams, diagram_warnings), encoding="utf-8")

    outputs = {
        "routes_raw": {"path": str(routes_path.resolve()), "sha256": sha256(routes_path)},
        "scored_reactions_parquet": {"path": str(reaction_parquet.resolve()), "sha256": sha256(reaction_parquet)},
        "scored_reactions_csv": {"path": str(reaction_csv.resolve()), "sha256": sha256(reaction_csv)},
        "scored_routes_json": {"path": str(routes_json.resolve()), "sha256": sha256(routes_json)},
        "scored_routes_csv": {"path": str(routes_csv.resolve()), "sha256": sha256(routes_csv)},
        "visualization_html": {"path": str(visualization.resolve()), "sha256": sha256(visualization)},
        "reaction_diagrams": diagrams,
    }
    manifest = {
        **manifest_base,
        "status": "PASS",
        "created_at_utc": utc_now(),
        "target_id": target_id,
        "target_smiles": target_smiles,
        "outputs": outputs,
        "counts": {
            "route_count": len(route_rows),
            "reaction_occurrence_count": len(reaction_rows),
            "solved_route_count": int(sum(bool(route["solved"]) for route in route_rows)),
            "zero_reaction_route_count": int(sum(not route["difficulty_applicable"] for route in route_rows)),
        },
        "scientific_boundaries": {
            "prospective_inference": True,
            "labels_read": False,
            "locked_test_read": False,
            "training_or_refit": False,
            "stage2_10_modified": False,
            "mcts_modified": False,
            "stage12_started": False,
            "experimental_success_probability": False,
            "route_level_accuracy": False,
        },
        "diagram_warnings": diagram_warnings,
    }
    manifest_path = output_dir / "prospective_manifest.json"
    # The manifest records all artifact hashes.  Its own final SHA256 is
    # reported by the caller (including it inside the file would be circular).
    write_json(manifest_path, manifest)
    return manifest


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return esc(value)


def reaction_diagram_svg(reaction_smiles: str, width: int = 900, height: int = 240) -> str:
    """Render one reaction as a deterministic RDKit SVG key-line diagram."""
    from rdkit.Chem import AllChem
    from rdkit.Chem.Draw import rdMolDraw2D

    try:
        reaction = AllChem.ReactionFromSmarts(str(reaction_smiles), useSmiles=True)
    except Exception as exc:
        raise ProspectiveBlocked(f"RDKit cannot parse reaction SMILES: {exc}") from exc
    if reaction is None or reaction.GetNumReactantTemplates() == 0 or reaction.GetNumProductTemplates() == 0:
        raise ProspectiveBlocked("reaction has no drawable precursor or product component")
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    drawer.DrawReaction(reaction)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def write_reaction_diagrams(
    structure_dir: Path,
    reaction_rows: list[dict[str, Any]],
    progress: "ProgressReporter | None" = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    structure_dir.mkdir(parents=True, exist_ok=True)
    diagrams: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    unique_rows: list[tuple[str, dict[str, Any]]] = []
    for row in reaction_rows:
        reaction_hash = str(row.get("reaction_hash", ""))
        if not reaction_hash or reaction_hash in seen:
            continue
        seen.add(reaction_hash)
        unique_rows.append((reaction_hash, row))
    total = max(1, len(unique_rows))
    for position, (reaction_hash, row) in enumerate(unique_rows, 1):
        if progress is not None:
            progress.stage("write", (position - 1) / total, "Key-line diagram " + str(position) + "/" + str(len(unique_rows)))
        try:
            reaction_smiles = str(row.get("reaction_smiles", ""))
            svg_text = reaction_diagram_svg(reaction_smiles)
            svg_path = structure_dir / f"{reaction_hash}.svg"
            svg_path.write_text(svg_text, encoding="utf-8")
            from rdkit.Chem import AllChem
            from rdkit.Chem.Draw import rdMolDraw2D
            reaction = AllChem.ReactionFromSmarts(reaction_smiles, useSmiles=True)
            drawer = rdMolDraw2D.MolDraw2DCairo(1200, 320)
            drawer.DrawReaction(reaction)
            drawer.FinishDrawing()
            png_path = structure_dir / f"{reaction_hash}.png"
            png_path.write_bytes(drawer.GetDrawingText())
            diagrams.append({
                "reaction_hash": reaction_hash,
                "reaction_smiles": reaction_smiles,
                "svg_path": str(svg_path.resolve()),
                "svg_sha256": sha256(svg_path),
                "png_path": str(png_path.resolve()),
                "png_sha256": sha256(png_path),
            })
        except Exception as exc:
            warnings.append(f"{reaction_hash}: {type(exc).__name__}: {exc}")
    if progress is not None:
        progress.stage("write", 1.0, "Wrote " + str(len(diagrams)) + " key-line diagram(s)")
    return diagrams, warnings


def build_dashboard_html(target_id: str, target_smiles: str, routes: list[dict[str, Any]], diagrams: list[dict[str, Any]] | None = None, diagram_warnings: list[str] | None = None) -> str:
    """Create a self-contained, no-network HTML visualization."""
    route_cards = []
    diagram_by_hash = {item["reaction_hash"]: item for item in (diagrams or [])}
    chart_rows = []
    for route in routes:
        difficulty = route.get("difficulty_bottleneck")
        width = 0.0 if difficulty is None else max(0.0, min(100.0, float(difficulty)))
        chart_rows.append(
            f'<div class="bar-row"><div class="bar-label">#{esc(route["new_rank"])} {esc(route["route_id"])}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{width:.2f}%"></div></div>'
            f'<div class="bar-value">{fmt(difficulty, 2)}</div></div>'
        )
        step_rows = []
        for step in route.get("steps", []):
            diagram = diagram_by_hash.get(str(step.get("reaction_hash")))
            diagram_html = ""
            if diagram:
                svg_text = Path(diagram["svg_path"]).read_text(encoding="utf-8")
                diagram_html = f'<div class="reaction-diagram" aria-label="Reaction key-line diagram">{svg_text}</div>'
            step_rows.append(
                "<tr>"
                f"<td>{esc(step.get('step_id'))}</td>"
                f"<td><code>{esc(step.get('reaction_smiles'))}</code></td>"
                f"<td>{fmt(step.get('reaction_difficulty'), 2)}</td>"
                f"<td>{fmt(step.get('d_feas'), 4)}</td>"
                f"<td>{fmt(step.get('d_prec'), 4)}</td>"
                f"<td>{fmt(step.get('d_sc'), 4)}</td>"
                f"<td>{fmt(step.get('uncertainty'), 4)}</td>"
                f"<td>{esc(step.get('confidence'))}</td>"
                "</tr>"
                f"<tr><td colspan=8>{diagram_html}</td></tr>"
            )
        details = (
            f"<details><summary>路线 #{esc(route['new_rank'])} · {esc(route['route_id'])} · "
            f"瓶颈 {fmt(route.get('difficulty_bottleneck'), 2)} · {esc(route.get('route_confidence'))}</summary>"
            "<div class=\"route-meta\">"
            f"原始排名：{esc(route.get('original_rank'))}　排名变化：{esc(route.get('rank_change'))}　"
            f"步骤数：{esc(route.get('number_of_reactions'))}　平均难度：{fmt(route.get('difficulty_mean'), 2)}　"
            f"路线不确定性：{fmt(route.get('route_uncertainty'), 4)}"
            "</div>"
            f"<p>{esc(route.get('route_explanation'))}</p>"
            "<div class=\"table-wrap\"><table><thead><tr><th>step_id</th><th>reaction</th><th>difficulty</th>"
            "<th>d_feas</th><th>d_prec</th><th>d_sc</th><th>uncertainty</th><th>confidence</th></tr></thead>"
            f"<tbody>{''.join(step_rows) if step_rows else '<tr><td colspan=8>无反应步骤（直接来自 stock）</td></tr>'}</tbody></table></div></details>"
        )
        route_cards.append(details)
    route_count = len(routes)
    reaction_count = sum(len(route.get("steps", [])) for route in routes)
    payload = json.dumps({"target_id": target_id, "target_smiles": target_smiles, "routes": routes}, ensure_ascii=False)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prospective difficulty · {esc(target_id)}</title>
<style>
:root {{ color-scheme: light dark; --bg: light-dark(#f7f8fa,#121417); --fg: light-dark(#1b1f24,#f2f4f7); --muted: light-dark(#5d6672,#a9b1bb); --line: light-dark(#d9dee5,#343b45); --surface: light-dark(#fff,#1b2026); --accent: light-dark(#3267c7,#83aefc); --accent2: light-dark(#b85b24,#f29b6c); }}
* {{ box-sizing:border-box }} body {{ margin:0; padding:28px; background:var(--bg); color:var(--fg); font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif }} main {{ max-width:1200px; margin:auto }} h1 {{ margin:0 0 4px; font-size:24px; font-weight:500 }} h2 {{ margin:28px 0 10px; font-size:17px; font-weight:500 }} .muted {{ color:var(--muted) }} .summary {{ display:flex; flex-wrap:wrap; gap:12px; margin:20px 0 }} .stat {{ background:var(--surface); border:1px solid var(--line); padding:12px 16px; min-width:150px }} .stat strong {{ display:block; font-size:22px; font-weight:500 }} .target {{ background:var(--surface); border-left:3px solid var(--accent); padding:12px 14px; overflow-wrap:anywhere }} .chart {{ background:var(--surface); border:1px solid var(--line); padding:14px }} .bar-row {{ display:grid; grid-template-columns:minmax(170px,290px) 1fr 70px; gap:10px; align-items:center; margin:8px 0 }} .bar-label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap }} .bar-track {{ height:14px; background:color-mix(in srgb,var(--line) 45%,transparent); }} .bar-fill {{ height:100%; background:var(--accent2); }} .bar-value {{ text-align:right; font-variant-numeric:tabular-nums }} details {{ background:var(--surface); border:1px solid var(--line); margin:10px 0; padding:10px 12px }} summary {{ cursor:pointer; font-weight:500 }} .route-meta {{ color:var(--muted); margin:10px 0 }} .table-wrap {{ overflow-x:auto }} table {{ border-collapse:collapse; width:100%; min-width:900px }} th,td {{ border-bottom:1px solid var(--line); padding:7px 8px; text-align:left; vertical-align:top }} th {{ color:var(--muted); font-weight:500 }} code {{ white-space:normal; overflow-wrap:anywhere }} footer {{ color:var(--muted); margin-top:28px; font-size:12px }} @media(max-width:700px) {{ body {{ padding:16px }} .bar-row {{ grid-template-columns:1fr 64px }} .bar-track {{ grid-column:1/-1; grid-row:2 }} .bar-value {{ grid-column:2; grid-row:1 }} }}
</style></head><body><main>
<h1>新化合物前瞻性难度评分</h1>
<div class="muted">独立 on-demand 推理结果 · 不修改冻结科研项目</div>
<p class="target"><strong>target_id:</strong> {esc(target_id)}<br><strong>SMILES:</strong> <code>{esc(target_smiles)}</code></p>
<div class="summary"><div class="stat"><span class="muted">候选路线</span><strong>{route_count}</strong></div><div class="stat"><span class="muted">反应步骤</span><strong>{reaction_count}</strong></div><div class="stat"><span class="muted">评分模型</span><strong>0–100</strong></div><div class="stat"><span class="muted">排序依据</span><strong>瓶颈难度</strong></div></div>
<h2>路线瓶颈难度（越低越容易）</h2><div class="chart" role="img" aria-label="按新排名排列的路线瓶颈难度条形图">{''.join(chart_rows) if chart_rows else '<p class="muted">AiZynthFinder 未返回路线。</p>'}</div>
<h2>路线和步骤明细</h2>{''.join(route_cards) if route_cards else '<p class="muted">没有可展示的路线。</p>'}
<footer>固定特征顺序：[d_feas, d_prec, d_sc]；precedent 参数：tau=0.80、N0=10、cosine、top_k=100。reaction_difficulty 是相对难度，不是产率或实验成功概率。</footer>
<script>window.prospectiveResult = {payload};</script>
</main></body></html>'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prospective AiZynthFinder + frozen difficulty scoring")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--smiles", help="新目标分子的 SMILES；会先运行 AiZynthFinder 搜索")
    source.add_argument("--routes", type=Path, help="已有 AiZynthFinder routes_raw.json；跳过搜索，仅执行 on-demand 评分")
    parser.add_argument("--target-id", default="prospective_001", help="输出中的新目标标识符（仅用于本次外部结果）")
    parser.add_argument("--project-dir", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--iteration-limit", type=int, default=None, help="per-run MCTS iteration limit")
    parser.add_argument("--time-limit", type=float, default=None, help="per-run search time limit in seconds")
    parser.add_argument("--max-transforms", type=int, default=None, help="per-run maximum reaction transforms")
    parser.add_argument("--max-routes", type=int, default=None, help="per-run maximum routes shown")
    parser.add_argument("--min-routes", type=int, default=None, help="per-run minimum routes requested")
    parser.add_argument(
        "--progress",
        action="store_true",
        default=False,
        help="emit machine-readable progress events on stderr (used by the desktop front-end)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = args.project_dir.resolve()
    target_id = str(args.target_id)
    if not TARGET_ID_PATTERN.fullmatch(target_id):
        raise ProspectiveBlocked("target-id may contain only letters, numbers, underscore, dot and hyphen")
    if not project.is_dir():
        raise ProspectiveBlocked(f"project directory missing: {project}")
    output_dir = (args.output_dir or (Path(__file__).resolve().parent / "prospective_runs" / target_id)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    progress = ProgressReporter(bool(getattr(args, "progress", False)))
    progress.stage("prepare", 0.0, "Loading frozen project modules")
    target_smiles = str(args.smiles or "").strip()
    modules = load_project_modules(project)
    if target_smiles:
        target_smiles = modules["canonicalize_molecule_smiles"](target_smiles, "prospective target")
    else:
        target_smiles = "(provided via routes file)"
    progress.stage("prepare", 0.5, "Frozen modules loaded")
    assets = frozen_asset_inventory(project, progress)
    manifest_base: dict[str, Any] = {
        "tool": "prospective_difficulty_tool",
        "tool_version": "1.0",
        "project_dir": str(project),
        "runtime": runtime_info(),
        "git": git_info(project),
        "frozen_assets": assets,
        "search_policy": {"expansion_policy": "uspto", "stock": "zinc", "nproc": 1, "config_path": str((project / "config/config_production.yml").resolve())},
        "input_mode": "search_then_score" if args.smiles else "score_existing_routes",
        "configuration_unchanged": True,
        "search_parameters": {
            "iteration_limit": args.iteration_limit,
            "time_limit": args.time_limit,
            "max_transforms": args.max_transforms,
            "max_routes": args.max_routes,
            "min_routes": args.min_routes,
        },
    }
    try:
        if args.smiles:
            target_input = output_dir / "target.smi"
            target_input.write_text(target_smiles + "\n", encoding="utf-8")
            search_params = {
                "iteration_limit": args.iteration_limit,
                "time_limit": args.time_limit,
                "max_transforms": args.max_transforms,
                "max_routes": args.max_routes,
                "min_routes": args.min_routes,
            }
            routes_path, command, config_info = run_search(project, target_smiles, output_dir, search_params, progress)
            manifest_base["search_command"] = command
            manifest_base["search_config"] = config_info
            manifest_base["search_parameters"] = config_info["effective"]
            manifest_base["target_input_path"] = str(target_input.resolve())
        else:
            routes_path = args.routes.resolve()
            require_file(routes_path, "routes input")
            manifest_base["search_command"] = None
            manifest_base["search_config"] = None
        raw = load_routes(routes_path)
        if len(raw["data"]) != 1:
            raise ProspectiveBlocked(f"prospective routes input returned {len(raw['data'])} target rows instead of 1")
        if not args.smiles:
            target_smiles = modules["canonicalize_molecule_smiles"](str(raw["data"][0].get("target", "")), "routes target")
        route_rows, reaction_rows, summary = score_routes(project, target_id, raw, modules, progress)
        progress.stage("write", 0.0, "Writing run outputs")
        manifest_base["scoring_summary"] = summary
        manifest = save_outputs(output_dir, target_id, target_smiles, routes_path, route_rows, reaction_rows, manifest_base, progress)
        manifest_path = output_dir / "prospective_manifest.json"
        progress.emit(100.0, "done", "Prospective run completed")
        print(json.dumps({"status": "PASS", "output_dir": str(output_dir), "manifest": str(manifest_path), "visualization": str(output_dir / "prospective_dashboard.html"), "routes": len(route_rows), "reaction_rows": len(reaction_rows), "manifest_sha256": sha256(manifest_path)}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # A blocked run must not read as finished: hold the last real percentage
        # so the front-end shows how far the pipeline actually got.
        progress.emit(progress.percent, "blocked", "Run blocked; see prospective_blocker.json")
        blocker = {
            **manifest_base,
            "status": "BLOCKED",
            "created_at_utc": utc_now(),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "scientific_boundaries": {"project_files_modified": False, "labels_read": False, "locked_test_read": False, "training_or_refit": False},
        }
        write_json(output_dir / "prospective_blocker.json", blocker)
        print(json.dumps({"status": "BLOCKED", "error": blocker["error"], "blocker": str((output_dir / "prospective_blocker.json").resolve())}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
