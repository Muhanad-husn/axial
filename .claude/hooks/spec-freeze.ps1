# Spec-freeze gate. Global PreToolUse hook on Edit|Write: specs/ is frozen during
# implementation. Reads tool input as JSON on stdin; exits 2 (block) on any write
# under specs/ unless spec-authoring mode is on.
#
# Toggle: spec mode is ON when the flag file .claude/spec-mode exists. The founder
# enables it by saying so; the orchestrator creates the flag, dispatches the
# spec-author, then removes it. The spec-author's own frontmatter guard still
# confines it to specs/ while the freeze is lifted.

$ErrorActionPreference = 'Stop'

try { $j = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
$filePath = "$($j.tool_input.file_path)"
if (-not $filePath) { exit 0 }

$projectDir = $env:CLAUDE_PROJECT_DIR
if (-not $projectDir) { $projectDir = Split-Path (Split-Path $PSScriptRoot) }

$full = [System.IO.Path]::GetFullPath($filePath)
$root = [System.IO.Path]::GetFullPath($projectDir)
if (-not $full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { exit 0 }
$rel = $full.Substring($root.Length).TrimStart('\', '/').Replace('\', '/')

if ($rel -match '^specs/') {
    if (Test-Path (Join-Path $projectDir '.claude/spec-mode')) { exit 0 }
    [Console]::Error.WriteLine("BLOCKED: specs/ is frozen during implementation. Spec changes route through a spec-drift issue and a founder-enabled spec-authoring pass (.claude/spec-mode).")
    exit 2
}

exit 0
