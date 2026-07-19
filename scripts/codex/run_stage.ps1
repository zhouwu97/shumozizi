param(
    [Parameter(Mandatory = $true)]
    [string]$RunId,
    [Parameter(Mandatory = $true)]
    [string]$Prompt
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$runDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "runs\$RunId"))
$runsRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "runs"))
if (-not $runDir.StartsWith($runsRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "RunId escapes the runs directory"
}
if (-not (Test-Path -LiteralPath (Join-Path $runDir "state.json"))) {
    throw "Missing workflow state: $runDir\state.json"
}

$logDir = Join-Path $runDir "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$eventLog = Join-Path $logDir "events.jsonl"
$errorLog = Join-Path $logDir "progress.log"

Push-Location $repoRoot
try {
    codex exec --sandbox workspace-write --json $Prompt 2> $errorLog | Tee-Object -FilePath $eventLog
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}
