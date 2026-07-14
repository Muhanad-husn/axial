# Role path guard (roster path rules). PreToolUse hook on Edit|Write. Reads tool
# input as JSON on stdin; exits 2 (block) when the target path violates the role's
# boundary.
#
#   spec-author  -> may write ONLY under specs/
#   test-author  -> may write ONLY under tests/
#   implementer  -> may write anywhere EXCEPT tests/ and specs/
#   fixer        -> may write anywhere EXCEPT tests/ and specs/ (fix lane, same scope)
#
# Two wirings, one script (DEC-18): role frontmatter passes the role name
# explicitly; the global settings.json wiring passes no arg and the role is taken
# from stdin agent_type. Non-role agents and the main session pass through.

param([string]$Role = '')

$ErrorActionPreference = 'Stop'

function Block([string]$reason) {
    [Console]::Error.WriteLine("BLOCKED by path guard ($Role): $reason")
    exit 2
}

try { $j = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
if (-not $Role) { $Role = "$($j.agent_type)" }
if (-not $Role) { exit 0 }
$filePath = "$($j.tool_input.file_path)"
if (-not $filePath) { exit 0 }

# Resolve the project root from the TARGET FILE'S own git worktree, not the tool
# call's cwd. A role subagent fanned out from the main session reports its
# launch-checkout cwd (e.g. D:\axial) on Edit|Write even when the file it targets
# lives in a sibling worktree (e.g. D:\axial-guard); a cwd-based root then mis-scoped
# the role rule and blocked the legitimate write. The file's own path unambiguously
# identifies the worktree it belongs to, and the role boundary (tests/ vs src/ vs
# specs/) is a shape rule *within* that worktree -- so resolve from the file. Walk up
# to the nearest existing ancestor first, since the file (or its immediate parent
# dir) may not exist yet.
$full = [System.IO.Path]::GetFullPath($filePath)
$probe = Split-Path -Parent $full
while ($probe -and -not (Test-Path -LiteralPath $probe)) { $probe = Split-Path -Parent $probe }
if (-not $probe) { Block "cannot resolve a directory for the target path ($filePath)." }
# git errors on a non-repo dir; under ErrorActionPreference=Stop that surfaces as a
# terminating NativeCommandError, so catch it and treat "no root" as a clean block.
$projectDir = $null
try { $projectDir = (& git -C $probe rev-parse --show-toplevel 2>$null) } catch { $projectDir = $null }
if (-not $projectDir) { Block "target is not inside a git worktree ($filePath)." }

# Normalize to a project-relative forward-slash path. $full is under $projectDir by
# construction (the root is the git toplevel of one of $full's ancestors), so a
# length-based substring yields the project-relative path regardless of separator case.
$rootTrim = [System.IO.Path]::GetFullPath($projectDir).TrimEnd('\', '/')
$rel = $full.Substring($rootTrim.Length).TrimStart('\', '/').Replace('\', '/')

switch ($Role) {
    'spec-author' {
        if ($rel -notmatch '^specs/') { Block "spec-author may write only under specs/ (tried: $rel)." }
    }
    'test-author' {
        if ($rel -notmatch '^tests/') { Block "test-author may write only under tests/ (tried: $rel)." }
    }
    'implementer' {
        if ($rel -match '^tests/') { Block "implementer may not touch tests/ - the outer contract is locked (DEC-1) (tried: $rel)." }
        if ($rel -match '^specs/') { Block "implementer may not touch specs/ - raise a spec-drift issue instead (tried: $rel)." }
    }
    'fixer' {
        if ($rel -match '^tests/') { Block "fixer may not touch tests/ - regression tests come from the test-author (tried: $rel)." }
        if ($rel -match '^specs/') { Block "fixer may not touch specs/ - feature-scale work belongs in a slice via /sprint-start (tried: $rel)." }
    }
    default {
        # Not one of the three path-ruled roles (orchestrator, triage, reviewer,
        # utility agents): no path restriction from this guard.
        exit 0
    }
}

exit 0
