param(
    [Parameter(Mandatory = $true)]
    [string]$RunId
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$statePath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "runs\$RunId\state.json"))
if (-not (Test-Path -LiteralPath $statePath)) {
    throw "Missing workflow state: $statePath"
}
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
$prompt = "Use `$mathmodel-workflow to read runs/$RunId/state.json, continue from status $($state.status), and stop at the next required human checkpoint."
& (Join-Path $PSScriptRoot "run_stage.ps1") -RunId $RunId -Prompt $prompt
exit $LASTEXITCODE
