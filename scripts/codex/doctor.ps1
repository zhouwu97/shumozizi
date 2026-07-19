param()

$ErrorActionPreference = "Stop"
$tools = @(
    @{ Name = "Python"; Command = "python"; Args = @("--version"); Required = $true },
    @{ Name = "Codex"; Command = "codex"; Args = @("--version"); Required = $true },
    @{ Name = "Typst"; Command = "typst"; Args = @("--version"); Required = $false },
    @{ Name = "XeLaTeX"; Command = "xelatex"; Args = @("--version"); Required = $false }
)

$failedRequired = $false
foreach ($tool in $tools) {
    $resolved = Get-Command $tool.Command -ErrorAction SilentlyContinue
    if (-not $resolved) {
        $level = if ($tool.Required) { "ERROR" } else { "WARN" }
        Write-Output "[$level] $($tool.Name): command not found"
        if ($tool.Required) { $failedRequired = $true }
        continue
    }
    try {
        $version = & $tool.Command @($tool.Args) 2>&1 | Select-Object -First 1
        Write-Output "[OK] $($tool.Name): $version"
    }
    catch {
        $level = if ($tool.Required) { "ERROR" } else { "WARN" }
        Write-Output "[$level] $($tool.Name): found but not executable - $($_.Exception.Message)"
        if ($tool.Required) { $failedRequired = $true }
    }
}

if ($failedRequired) { exit 1 }
exit 0
