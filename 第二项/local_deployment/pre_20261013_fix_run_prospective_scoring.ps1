param(
    [Parameter(Mandatory = $true)]
    [string]$Smiles,
    [string]$TargetId = "prospective_001",
    [string]$OutputDir = "",
    [string]$ProjectDir = "",
    [string]$Python = "",
    [Nullable[int]]$IterationLimit = $null,
    [Nullable[double]]$TimeLimit = $null,
    [Nullable[int]]$MaxTransforms = $null,
    [Nullable[int]]$MaxRoutes = $null,
    [Nullable[int]]$MinRoutes = $null
)

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 can leave PSScriptRoot empty while evaluating param
# defaults. Resolve package paths after parameter binding instead.
$PackageRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) { $OutputDir = Join-Path $PackageRoot "prospective_runs\$TargetId" }
if (-not $ProjectDir) { $ProjectDir = Join-Path $PackageRoot "frozen_project" }
if (-not $Python) {
    $UserConfig = Join-Path $PackageRoot "portable_config.ps1"
    if (Test-Path -LiteralPath $UserConfig -PathType Leaf) { . $UserConfig }
    $Python = if ($env:AIZYNTH_PYTHON) { $env:AIZYNTH_PYTHON } else { "python.exe" }
}
$tool = Join-Path $PSScriptRoot "prospective_score.py"
if ($Python -ne "python.exe" -and $Python -ne "python" -and -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python executable not found: $Python"
}
if (-not (Test-Path -LiteralPath $ProjectDir -PathType Container)) {
    throw "Frozen project directory not found: $ProjectDir"
}

$extra = @()
if ($null -ne $IterationLimit) { $extra += @('--iteration-limit', [string]$IterationLimit) }
if ($null -ne $TimeLimit) { $extra += @('--time-limit', [string]$TimeLimit) }
if ($null -ne $MaxTransforms) { $extra += @('--max-transforms', [string]$MaxTransforms) }
if ($null -ne $MaxRoutes) { $extra += @('--max-routes', [string]$MaxRoutes) }
if ($null -ne $MinRoutes) { $extra += @('--min-routes', [string]$MinRoutes) }

& $Python -s $tool --project-dir $ProjectDir --smiles $Smiles --target-id $TargetId --output-dir $OutputDir @extra
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Completed. Dashboard: $OutputDir\prospective_dashboard.html"
