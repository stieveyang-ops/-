param(
    [Parameter(Mandatory = $true)]
    [string]$CondaExe
)

$ErrorActionPreference = "Stop"
$PackageRoot = $PSScriptRoot
$Copied = Join-Path $PackageRoot "frozen_project\.conda-rxnfp"
$Target = Join-Path $PackageRoot "frozen_project\.conda-rxnfp-local"
$Lock = Join-Path $PackageRoot "frozen_project\requirements-rxnfp-lock.txt"

if (-not (Test-Path -LiteralPath $CondaExe -PathType Leaf)) { throw "Conda executable not found: $CondaExe" }
if (Test-Path -LiteralPath $Target) { throw "Local RXNFP target already exists: $Target. It will not be overwritten." }

& $CondaExe create --prefix $Target python=3.8 pip -y
if ($LASTEXITCODE -ne 0) { throw "Conda environment creation failed." }
$Python = Join-Path $Target "python.exe"
& $Python -m pip install -r $Lock
if ($LASTEXITCODE -ne 0) { throw "RXNFP dependency installation failed." }

Write-Host "RXNFP environment created at: $Target"
Write-Host "The copied environment remains preserved at: $Copied"
Write-Host "Run switch_to_local_rxnfp.ps1, then launch_gui.cmd."
