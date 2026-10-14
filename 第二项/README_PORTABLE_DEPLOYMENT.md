# AIZynthFinder reaction-difficulty portable deployment

This directory is a copied, versioned deployment package. It is independent
of the original `aizynth-reaction-difficulty` working tree and does not move,
edit, retrain, or recompute any Stage 1-11 artifact.

## What is included

- `prospective_difficulty_tool/`: GUI, command-line wrapper and on-demand
  scorer for new compounds.
- `frozen_project/`: copied source modules, read-only configurations, frozen
  Stage 2-11 data/artifacts, and the isolated RXNFP runtime copy.
- `external_public_data/public_data/`: USPTO expansion/filter/ringbreaker
  assets and ZINC stock.
- `package_reference_sha256.csv`: required-file inventory and SHA256/size
  baseline.
- `package_completeness_test.ps1`: fail-closed package test.
- `validate_environment.py`: dependency, asset and real RXNFP embedding test.

The package deliberately excludes `.git` history, cache folders, old smoke
outputs, temporary work directories, and the original machine-wide Conda
environment. These are explicit exclusions, not silent omissions; see
`package_completeness_report.json` after running the test.

## New computer setup (manual steps)

1. Copy the entire folder to any local disk/path. Do not copy only selected
   subfolders. The package does not require the original project path.
2. Install or select a writable Python 3.10 environment on the new computer.
   It must provide the versions recorded in `frozen_project/requirements-lock.txt`,
   especially AiZynthFinder 4.4.1, RDKit 2023.9.6, NumPy 1.26.4, pandas 2.3.3,
   PyArrow 25.0.0, SciPy 1.15.2, statsmodels 0.14.4 and ONNX Runtime 1.23.2.
   Do not use `--user` packages or substitute/random models.
   The concise version list is also in `requirements-portable-main.txt`. A
   typical Conda-forge setup is:

   ```powershell
   conda create --prefix "C:\Tools\CondaEnvs\aizynth-portable" python=3.10.20 -y
   conda activate "C:\Tools\CondaEnvs\aizynth-portable"
   conda install -c conda-forge rdkit=2023.9.6 numpy=1.26.4 pandas=2.3.3 pyarrow=25.0.0 scipy=1.15.2 scikit-learn=1.5.2 statsmodels=0.14.4 pyyaml=6.0.3 joblib=1.5.3 tables=3.10.1 pillow=12.3.0 -y
   python -m pip install aizynthfinder==4.4.1 onnxruntime==1.23.2 reaction-utils==1.9.3
   ```

   If a package manager cannot provide these exact versions, stop and record
   the failure; do not downgrade/upgrade silently or use user-site packages.
3. Copy `portable_config.example.ps1` to `portable_config.ps1` and edit only
   the Python executable, for example:

   ```powershell
   $env:AIZYNTH_PYTHON = "C:\Tools\Miniconda\envs\aizynth\python.exe"
   ```

4. From this package directory, run:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\package_completeness_test.ps1
   ```

   Continue only when `package_completeness_report.json` says `PASS` and
   `environment_validation.json` says `PASS`.
5. Double-click `launch_gui.cmd` (or run it from PowerShell). The launcher
   validates before opening the GUI and stops on any missing/mismatched asset.

## Non-ASCII install path (fixed 2026-10-13)

AiZynthFinder 4.4.1 reads its YAML configuration with the process locale
encoding. If this package is installed under a path containing non-ASCII
characters on a Windows locale whose code page is cp936/GBK, that read fails
with `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae ...` and the tool
stops with a `BLOCKED` run.

The three entry points (`launch_gui.cmd`, `launch_gui.ps1` and
`prospective_difficulty_tool/run_prospective_scoring.ps1`) now set
`PYTHONUTF8=1` before starting Python, so every child process (GUI, scorer and
AiZynthFinder) inherits UTF-8 mode. No manual environment variable is needed,
and no model, configuration or frozen artifact is affected. Installing the
package under a pure-ASCII path avoids the issue entirely.

Pre-fix copies of the three scripts are kept in `local_deployment/` as
`pre_20261013_fix_launch_gui.cmd`, `pre_20261013_fix_launch_gui.ps1` and
`pre_20261013_fix_run_prospective_scoring.ps1`.

The completeness test creates `package_files_sha256.csv`,
`package_completeness_report.json` and a validation log. These are local audit
outputs; they are not Stage 1-11 scientific artifacts.

## If the copied RXNFP runtime does not work

The bundled `.conda-rxnfp` is a source-machine copy and may fail on another
Windows installation because Conda embeds machine-specific prefixes/DLLs.
Preserve it; do not delete or overwrite it. Install Conda on the target
computer, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\rebuild_rxnfp_environment.ps1 `
  -CondaExe "C:\Path\To\conda.exe"
```

This creates `.conda-rxnfp-local` and refuses to overwrite an existing one.
After verifying it, run `switch_to_local_rxnfp.ps1`; that preserves the copied
runtime as `.conda-rxnfp-source-machine-copy` and activates the rebuilt one.
Run `package_completeness_test.ps1` again before using the GUI.

## Running a new compound

GUI: enter SMILES and Target ID, adjust iteration limit, time limit, maximum
reaction steps, maximum routes and minimum routes, then click **RUN SEARCH AND
SHOW ROUTES**. A new timestamped directory is created under `prospective_runs`.
The dashboard includes ranked routes and RDKit key-line reaction diagrams.

CLI example (all paths are package-relative):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\prospective_difficulty_tool\run_prospective_scoring.ps1 `
  -Smiles "Cc1ccccc1.O=C(O)c1ccccc1" `
  -TargetId "my_compound_003" `
  -IterationLimit 200 `
  -TimeLimit 120 `
  -MaxTransforms 6 `
  -MaxRoutes 10 `
  -MinRoutes 3
```

For every run, inspect `prospective_manifest.json`; it records the effective
search parameters and SHA256 of frozen assets. A `BLOCKED` run is a hard stop.
Do not bypass it with another model or by editing a frozen artifact.

## Scientific boundary

This tool performs only prospective search followed by on-demand scoring for a
new target. It does not change Stage 1-11 data, labels, locked-test files,
models, rankings, manifests or release artifacts, and it does not start Stage
12. `reaction_difficulty` is a difficulty score, not a reaction-success
probability or route-level accuracy.
