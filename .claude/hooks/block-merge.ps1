# Subagents-never-merge gate (DEC-3). PreToolUse hook: reads tool input as JSON on
# stdin, exits 2 (block) on any merge / push-to-main / branch-delete attempt.
# Wired per-subagent in role frontmatter (Bash) and globally for the GitHub
# plugin's merge-capable tools. The orchestrator's own approved merge path is NOT
# wired through this script.

$ErrorActionPreference = 'Stop'

function Block([string]$reason) {
    [Console]::Error.WriteLine("BLOCKED: $reason Prepare the PR; the main session merges after founder approval.")
    exit 2
}

try { $j = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
$tool = "$($j.tool_name)"

if ($tool -like 'mcp__*') {
    if ($tool -match 'merge_pull_request$' -or $tool -match 'merge') {
        Block "subagents and the plugin merge tool never merge."
    }
    if ($tool -match '(create_or_update_file|push_files|delete_file)$') {
        $branch = "$($j.tool_input.branch)"
        if ($branch -eq 'main' -or $branch -eq 'refs/heads/main') {
            Block "no direct writes to main through the GitHub plugin."
        }
    }
    exit 0
}

if ($tool -eq 'Bash') {
    $cmd = "$($j.tool_input.command)"
    if ($cmd -match 'git\s+(\S+\s+)*merge')            { Block "subagents never run git merge." }
    if ($cmd -match 'gh\s+pr\s+merge')                 { Block "subagents never merge PRs." }
    if ($cmd -match 'gh\s+api\s+\S*merge')             { Block "subagents never merge via the API." }
    if ($cmd -match 'git\s+branch\s+(-d|-D|--delete)') { Block "subagents never delete branches; cleanup runs on founder approval." }
    if ($cmd -match 'git\s+push\s+.*--delete')         { Block "subagents never delete remote branches." }
    if ($cmd -match 'git\s+push') {
        if ($cmd -match '\bmain\b') { Block "subagents never push to main." }
        $projectDir = $env:CLAUDE_PROJECT_DIR
        if (-not $projectDir) { $projectDir = Split-Path (Split-Path $PSScriptRoot) }
        $current = (& git -C $projectDir rev-parse --abbrev-ref HEAD 2>$null)
        if ($current -eq 'main') { Block "subagents never push while on main." }
    }
    exit 0
}

exit 0
