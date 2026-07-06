# Tests-green-before-commit gate (DEC-3) + no-direct-commits-on-main. Global
# PreToolUse hook on Bash. Reads tool input as JSON on stdin; acts only when the
# command contains a git commit. Exits 2 (block) on a red suite or a commit on main.
#
# Escape hatch for DEC-1's one intended red commit (the outer acceptance test,
# committed red by the test-author): if the flag file .claude/allow-red-commit
# exists, the pytest check is skipped for that commit. The orchestrator creates and
# removes the flag on founder-approved outer-test commits only.

$ErrorActionPreference = 'Stop'

try { $j = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
$cmd = "$($j.tool_input.command)"
if ($cmd -notmatch 'git\s+(\S+\s+)*commit') { exit 0 }

$projectDir = $env:CLAUDE_PROJECT_DIR
if (-not $projectDir) { $projectDir = Split-Path (Split-Path $PSScriptRoot) }

$branch = (& git -C $projectDir rev-parse --abbrev-ref HEAD 2>$null)
if ($branch -eq 'main') {
    [Console]::Error.WriteLine("BLOCKED: no direct commits on main. Work on a branch; merge via PR after founder approval.")
    exit 2
}

if (Test-Path (Join-Path $projectDir '.claude/allow-red-commit')) { exit 0 }

Push-Location $projectDir
try { & uv run pytest -q 2>&1 | Out-Null; $green = ($LASTEXITCODE -eq 0) }
finally { Pop-Location }

if (-not $green) {
    [Console]::Error.WriteLine("BLOCKED: test suite is red. Get to green before committing (or, for the one intended red commit of an outer acceptance test, ask the orchestrator to set .claude/allow-red-commit with founder approval).")
    exit 2
}

exit 0
