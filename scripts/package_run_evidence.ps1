param(
    [Parameter(Mandatory = $true)]
    [string]$RunDir,
    [Parameter(Mandatory = $true)]
    [string]$OutputZip
)

$ErrorActionPreference = "Stop"
$run = (Resolve-Path -LiteralPath $RunDir).Path
$zip = [System.IO.Path]::GetFullPath($OutputZip)
$parent = Split-Path -Parent $zip
$runId = Split-Path -Leaf $run
$staging = Join-Path $parent ("._package_staging_" + $runId)
$stageRoot = Join-Path $staging $runId

if (Test-Path -LiteralPath $staging) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

$includedDirs = @(
    "analysis", "code", "figures", "input_cache", "knowledge", "logs",
    "paper", "problem", "qa", "reports", "results", "review", "state"
)
$excludedNames = @("__pycache__", ".git", ".pytest_cache")

foreach ($dir in $includedDirs) {
    $source = Join-Path $run $dir
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        continue
    }
    $destination = Join-Path $stageRoot $dir
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Get-ChildItem -LiteralPath $source -Recurse -File | Where-Object {
        $relativeParts = $_.FullName.Substring($source.Length).TrimStart('\').Split('\')
        ($excludedNames | Where-Object { $relativeParts -contains $_ }).Count -eq 0
    } | ForEach-Object {
        $relative = $_.FullName.Substring($source.Length).TrimStart('\')
        $target = Join-Path $destination $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target
    }
}

$readme = @"
主线运行成果归档

运行目录: $run
运行 ID: $runId
归档范围: 证据、结果、源码及其复核所需的分析、状态、题面附件和输入数据。
数据边界: 仅来自主线运行目录；未包含 dual_line 或其他运行目录。
完整性: PACKAGE_MANIFEST.json 记录归档文件的相对路径、字节数和 SHA-256。
源码: code/ 下为本运行实际使用的 Python 与 MATLAB 源码；Python 缓存已排除。
"@
Set-Content -LiteralPath (Join-Path $stageRoot "PACKAGE_README.txt") -Value $readme -Encoding UTF8

$files = Get-ChildItem -LiteralPath $stageRoot -Recurse -File | Sort-Object FullName
$entries = foreach ($file in $files) {
    $relative = $file.FullName.Substring($stageRoot.Length).TrimStart('\').Replace('\', '/')
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    [ordered]@{
        path = $relative
        size_bytes = [int64]$file.Length
        sha256 = $hash
    }
}

$manifest = [ordered]@{
    schema_version = "1.0"
    package_type = "cumcm-mainline-evidence-results-source"
    run_id = $runId
    source_run_dir = $run
    generated_at = [DateTime]::UtcNow.ToString("o")
    included_directories = $includedDirs
    excluded_directory_names = $excludedNames
    file_count = $entries.Count + 1
    files = @($entries)
}
$manifestPath = Join-Path $stageRoot "PACKAGE_MANIFEST.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Compress-Archive -LiteralPath $stageRoot -DestinationPath $zip -CompressionLevel Optimal
Remove-Item -LiteralPath $staging -Recurse -Force

$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
[ordered]@{
    archive = $zip
    archive_sha256 = $zipHash
    archive_size_bytes = (Get-Item -LiteralPath $zip).Length
    run_id = $runId
    file_count = $manifest.file_count
} | ConvertTo-Json
