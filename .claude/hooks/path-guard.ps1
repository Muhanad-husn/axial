# Role path guard (roster path rules). PreToolUse hook on Edit|Write. Reads tool
# input as JSON on stdin; exits 2 (block) when the target path violates the role's
# boundary.
#
#   spec-author  -> may write ONLY under specs/
#   test-author  -> may write ONLY under tests/
#   implementer  -> may write anywhere EXCEPT tests/ and specs/
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

# Resolve the worktree from the tool's cwd, not the session-fixed
# CLAUDE_PROJECT_DIR -- that stays bound to the launch checkout and mis-scopes
# role path rules for git-worktree sessions. Normalize to the git root of cwd.
$opDir = "$($j.cwd)"
if (-not $opDir) { $opDir = $env:CLAUDE_PROJECT_DIR }
if (-not $opDir) { $opDir = Split-Path (Split-Path $PSScriptRoot) }
$projectDir = (& git -C $opDir rev-parse --show-toplevel 2>$null)
if (-not $projectDir) { $projectDir = $opDir }

# Normalize to a project-relative forward-slash path. Require a trailing
# separator on the root so a sibling worktree sharing a name prefix
# (D:\axial-xref vs D:\axial) is not mistaken for being inside the project.
$full = [System.IO.Path]::GetFullPath($filePath)
$rootTrim = [System.IO.Path]::GetFullPath($projectDir).TrimEnd('\', '/')
$sep = [System.IO.Path]::DirectorySeparatorChar
if ($full -ne $rootTrim -and -not $full.StartsWith($rootTrim + $sep, [System.StringComparison]::OrdinalIgnoreCase)) {
    Block "this role may not write outside the project ($filePath)."
}
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
    default {
        # Not one of the three path-ruled roles (orchestrator, triage, reviewer,
        # utility agents): no path restriction from this guard.
        exit 0
    }
}

exit 0
