$ErrorActionPreference = "Stop"
$PackageRoot = $PSScriptRoot
$UserConfig = Join-Path $PackageRoot "portable_config.ps1"
if (Test-Path -LiteralPath $UserConfig -PathType Leaf) {
    . $UserConfig
}

function Resolve-AizynthPython {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:AIZYNTH_PYTHON) { $candidates.Add($env:AIZYNTH_PYTHON) }
    if ($env:CONDA_PREFIX) { $candidates.Add((Join-Path $env:CONDA_PREFIX "python.exe")) }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates.Add($command.Source) }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "No Python environment was found. Follow README_PORTABLE_DEPLOYMENT.md, then set AIZYNTH_PYTHON in portable_config.ps1."
}

$Python = Resolve-AizynthPython
$Validator = Join-Path $PackageRoot "validate_environment.py"
& $Python -s $Validator --package-root $PackageRoot --python $Python
if ($LASTEXITCODE -ne 0) {
    throw "Environment validation failed. Read environment_validation.json and README_PORTABLE_DEPLOYMENT.md."
}

$env:AIZYNTH_PYTHON = $Python
$Gui = Join-Path $PackageRoot "prospective_difficulty_tool\prospective_gui.py"
& $Python -s $Gui
exit $LASTEXITCODE
