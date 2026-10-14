$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Project = Join-Path $Root "frozen_project"
$Copied = Join-Path $Project ".conda-rxnfp"
$Local = Join-Path $Project ".conda-rxnfp-local"
$Preserved = Join-Path $Project ".conda-rxnfp-source-machine-copy"

if (-not (Test-Path -LiteralPath $Local -PathType Container)) { throw "Local RXNFP environment not found: $Local" }
if (Test-Path -LiteralPath $Preserved) { throw "Preserved RXNFP folder already exists: $Preserved" }
if (-not (Test-Path -LiteralPath $Copied -PathType Container)) { throw "Expected copied RXNFP folder not found: $Copied" }

Move-Item -LiteralPath $Copied -Destination $Preserved
Move-Item -LiteralPath $Local -Destination $Copied
Write-Host "Activated the rebuilt local RXNFP environment."
Write-Host "Preserved source-machine copy: $Preserved"
