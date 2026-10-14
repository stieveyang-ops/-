param([string]$Python = $(if ($env:AIZYNTH_PYTHON) { $env:AIZYNTH_PYTHON } else { "python.exe" }))
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$ReportPath = Join-Path $Root "package_completeness_report.json"
$HashCsv = Join-Path $Root "package_files_sha256.csv"
$errors = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]
function Add-Error([string]$Message) { [void]$errors.Add($Message) }
function Add-Warning([string]$Message) { [void]$warnings.Add($Message) }
function Rel([string]$Path) { return $Path.Substring($Root.Length).TrimStart('\').Replace('\','/') }
$required = @(
  "launch_gui.cmd", "launch_gui.ps1", "validate_environment.py", "README_PORTABLE_DEPLOYMENT.md", "requirements-portable-main.txt", "portable_config.example.ps1", "rebuild_rxnfp_environment.ps1", "switch_to_local_rxnfp.ps1", "portable_package_manifest.json", "package_reference_sha256.csv", "source_copy_verification.csv", "prospective_difficulty_tool/prospective_score.py", "prospective_difficulty_tool/prospective_gui.py", "frozen_project/config/config_production.yml", "frozen_project/reports/stage5_manifest.json", "frozen_project/reports/stage8_manifest.json", "frozen_project/artifacts/difficulty_model.pkl", "frozen_project/artifacts/reference_rxnfp.npy", "frozen_project/artifacts/reference_metadata.parquet", "frozen_project/artifacts/reference_nn_index.joblib", "frozen_project/artifacts/sc_delta_ecdf.npz", "frozen_project/data/reference/reference_reactions_clean.parquet", "external_public_data/public_data/uspto_model.onnx", "external_public_data/public_data/uspto_templates.csv.gz", "external_public_data/public_data/uspto_filter_model.onnx", "external_public_data/public_data/uspto_ringbreaker_model.onnx", "external_public_data/public_data/uspto_ringbreaker_templates.csv.gz", "external_public_data/public_data/zinc_stock.hdf5"
)
foreach ($item in $required) { if (-not (Test-Path -LiteralPath (Join-Path $Root $item) -PathType Leaf)) { Add-Error "Missing required file: $item" } }
$forbiddenDirs = @('.git','validation_run','portable_smoke_run','.pytest_cache','outputs','work')
$forbiddenFound = New-Object System.Collections.Generic.List[string]
foreach ($dirName in $forbiddenDirs) {
  $found = @(Get-ChildItem -LiteralPath $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $dirName -and $_.FullName -notlike '*\.conda-rxnfp\*' })
  foreach ($d in $found) { [void]$forbiddenFound.Add((Rel $d.FullName)) }
}
if ($forbiddenFound.Count) { Add-Error "Forbidden copied directories found ($($forbiddenFound.Count)); first entries: $((@($forbiddenFound) | Select-Object -First 20) -join ', ')" }
$referenceRows = Import-Csv -LiteralPath (Join-Path $Root "package_reference_sha256.csv")
$hashRows = New-Object System.Collections.Generic.List[object]
foreach ($row in $referenceRows) {
  $file = Join-Path $Root ($row.path -replace '/', '\')
  if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { Add-Error "Referenced hash file missing: $($row.path)"; continue }
  $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToUpperInvariant(); $size = (Get-Item -LiteralPath $file).Length
  $expectedHash = ([string]$row.sha256).Trim().ToUpperInvariant()
  $expectedSize = [int64](([string]$row.size_bytes).Trim())
  $match = (($actual -eq $expectedHash) -and ([int64]$size -eq $expectedSize))
  if (-not $match) { Add-Error "Hash or size mismatch: $($row.path) expected=$($row.sha256)/$($row.size_bytes) actual=$actual/$size" }
  $hashRows.Add([pscustomobject]@{path=$row.path; expected_sha256=$expectedHash; actual_sha256=$actual; expected_size_bytes=$expectedSize; actual_size_bytes=[int64]$size; match=$match; category=$row.category})
}
$hashRows | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath $HashCsv
$pythonInfo = [ordered]@{ executable=$Python; status="NOT_RUN"; log=(Join-Path $Root "package_completeness_validation.log"); exit_code=$null }
if ($Python -eq "python.exe" -or $Python -eq "python" -or (Test-Path -LiteralPath $Python -PathType Leaf)) {
  $validation = Join-Path $Root "validate_environment.py"; $tmp = Join-Path $Root "package_completeness_validation.log"
  & $Python -s $validation --package-root $Root --python $Python *> $tmp; $pythonInfo.exit_code = $LASTEXITCODE; $pythonInfo.status = if ($LASTEXITCODE -eq 0) { "PASS" } else { "BLOCKED" }
  if ($LASTEXITCODE -ne 0) { Add-Error "validate_environment.py failed; see package_completeness_validation.log" }
} else { Add-Warning "Python executable not found; environment validation was not run." }
$measure = Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike '*\package_completeness_validation.log' } | Measure-Object Length -Sum
$report = [pscustomobject]@{ status=if ($errors.Count -eq 0) { "PASS" } else { "BLOCKED" }; package_root=$Root; generated_at=(Get-Date).ToUniversalTime().ToString("o"); copy_semantics="Copied package; source was not moved or edited."; source_project_required_at_runtime=$false; included_top_level_components="prospective_difficulty_tool; frozen_project; external_public_data/public_data"; included_file_count=[int64]$measure.Count; included_bytes=[int64]$measure.Sum; excluded_items=".git metadata/history; cache directories; old validation/output directories; machine-wide Conda environment"; required_file_count=[int]$required.Count; forbidden_directories_found_count=[int]$forbiddenFound.Count; forbidden_directories_first_entries=(@($forbiddenFound | Select-Object -First 50) -join '; '); hash_inventory=$HashCsv; environment_validation_status=$pythonInfo.status; environment_validation_log=$pythonInfo.log; warnings=(@($warnings) -join '; '); errors=(@($errors) -join '; ') }
$json = $report | ConvertTo-Json -Depth 4; Set-Content -Encoding UTF8 -LiteralPath $ReportPath -Value $json; Write-Output $json
if ($errors.Count -gt 0) { exit 2 } else { exit 0 }
