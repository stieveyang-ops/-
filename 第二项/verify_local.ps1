$ErrorActionPreference = 'Stop'
$taskConfig = Join-Path $PSScriptRoot 'portable_config.ps1'
if (-not (Test-Path -LiteralPath $taskConfig -PathType Leaf)) {
    throw 'Missing portable_config.ps1. Configure the local Python environment first.'
}
. $taskConfig
if (-not $env:AIZYNTH_PYTHON) { throw 'AIZYNTH_PYTHON is not configured.' }
& (Join-Path $PSScriptRoot 'package_completeness_test.ps1') -Python $env:AIZYNTH_PYTHON
exit $LASTEXITCODE
