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

# Resolve the worktree this commit actually targets from the tool's cwd, not the
# session-fixed CLAUDE_PROJECT_DIR -- that stays bound to the launch checkout and
# misfires for git-worktree sessions (a commit in a feature worktree was blocked
# as "on main" because the launch checkout happened to be on main). Normalize to
# the git root of that cwd so the branch guard and pytest run against the tree
# being committed.
$opDir = "$($j.cwd)"
if (-not $opDir) { $opDir = $env:CLAUDE_PROJECT_DIR }
if (-not $opDir) { $opDir = Split-Path (Split-Path $PSScriptRoot) }
$projectDir = (& git -C $opDir rev-parse --show-toplevel 2>$null)
if (-not $projectDir) { $projectDir = $opDir }

$branch = (& git -C $projectDir rev-parse --abbrev-ref HEAD 2>$null)
if ($branch -eq 'main') {
    [Console]::Error.WriteLine("BLOCKED: no direct commits on main. Work on a branch; merge via PR after founder approval.")
    exit 2
}

if (Test-Path (Join-Path $projectDir '.claude/allow-red-commit')) { exit 0 }

# Docs-only fast path: if every file in this commit is documentation or a plan, the
# code test suite result cannot change, so skip pytest. This runs AFTER the main-branch
# block and the allow-red-commit escape hatch above, so neither is affected. Fails safe:
# it skips ONLY when certain the commit is docs-only; an empty set, any non-docs file, or
# any error falls through to the suite run below.
try {
    $staged = @(& git -C $projectDir diff --cached --name-only 2>$null | Where-Object { $_ })
    # `git commit -a/--all` sweeps in tracked-but-unstaged edits; fold them in so a code
    # file cannot ride along unseen. Detected generously - a false positive here only makes
    # us run the suite, never skip it.
    if ($cmd -match '(^|\s)-[A-Za-z]*a[A-Za-z]*(\s|$)' -or $cmd -match '--all\b') {
        $staged += @(& git -C $projectDir diff --name-only 2>$null | Where-Object { $_ })
    }
    $files = @($staged | Select-Object -Unique)
    $nonDocs = @($files | Where-Object { -not ($_ -imatch '\.(md|txt|rst)$' -or $_ -imatch '^(plans|docs)/') })
    if ($files.Count -gt 0 -and $nonDocs.Count -eq 0) {
        [Console]::Error.WriteLine("Docs-only commit ($($files.Count) file(s)); skipping the test suite - no code changed.")
        exit 0
    }
} catch { }  # any failure: fall through to the suite

# Fast per-commit gate (founder-approved policy): run only the hermetic src/ unit
# suite, in parallel across cores (pytest-xdist) -- ~6s for 220 tests. The heavy
# tests/ acceptance contracts drive the real docling pipeline end-to-end through
# many `uv run axial` subprocesses (~10 min) and share the data/ scratch dirs, so
# they are NOT run on every inner red-green commit. They still gate every PR: CI
# runs the full suite (required check) and safe-pr runs it locally before the PR.
# This keeps "no commit on a red suite" as a real, fast signal without re-running
# the full end-to-end pipeline on every commit.
Push-Location $projectDir
try { & uv run pytest src -q -m "not slow" -n auto 2>&1 | Out-Null; $green = ($LASTEXITCODE -eq 0) }
finally { Pop-Location }

if (-not $green) {
    [Console]::Error.WriteLine("BLOCKED: test suite is red. Get to green before committing (or, for the one intended red commit of an outer acceptance test, ask the orchestrator to set .claude/allow-red-commit with founder approval).")
    exit 2
}

exit 0
