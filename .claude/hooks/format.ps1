# PostToolUse formatter: ruff-format any edited Python file. Never blocks (exit 0).

try { $j = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
$filePath = "$($j.tool_input.file_path)"
if ($filePath -and $filePath -match '\.py$' -and (Test-Path $filePath)) {
    $projectDir = $env:CLAUDE_PROJECT_DIR
    if (-not $projectDir) { $projectDir = Split-Path (Split-Path $PSScriptRoot) }
    Push-Location $projectDir
    try { & uv run ruff format $filePath 2>$null | Out-Null } catch {} finally { Pop-Location }
}
exit 0
