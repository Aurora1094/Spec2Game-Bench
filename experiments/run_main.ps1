[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [string]$RunId = "main_r1",
    [string]$RoundId = "",
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"
$workspacePath = [System.IO.Path]::GetFullPath($Workspace)
if (-not [System.IO.Path]::IsPathFullyQualified($workspacePath)) {
    throw "Workspace must be an absolute path"
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$cliArguments = @(
    "main.py",
    "benchmark",
    "--workspace", $workspacePath,
    "--run-id", $RunId
)
if ($RoundId) { $cliArguments += @("--round-id", $RoundId) }
if ($Config) { $cliArguments += @("--config", $Config) }

$exitCode = 0
Push-Location $repositoryRoot
try {
    & python @cliArguments
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $exitCode
