# #784 slice 01: cost per ask, measured end to end on a real run.
# The issue's own bar -- "cost per ask is measured and reported, not
# estimated" -- and the last box on the slice's definition of done.
#
# Path: `axial ask` one-shot, which since this slice runs the same
# `axial.ask.paper.draft_paper_for_turn` the service worker calls. What is
# measured is the composition's real spend: the Phase-B answer plus the
# three Phase-C passes.
#
# ATTEMPT 1 HUNG AND WAS KILLED (attempt-1-blocked-on-fork.log). The
# intake fork check found a clarifying question -- Hinnebusch (1990) holds
# 57% of the 'Baath' notes for a question about power after 2011 -- and
# `cli._fork_prompt` blocked on stdin that a detached process does not
# have. It died at retrieval turn 5 of 14, after paying for the fork check
# and five retrieval calls. `axial ask` has no non-interactive flag, so the
# answer is piped in: "1" = keep all sources, with temporal guidance.
$env:AXIAL_SECRETS_PATH = $null
$log = "data/logs/2026-08-18-784-cost-per-ask"
$case = "Syria, 1920-2024 -- state formation and who the arrangement favoured"
$question = "Did the mandate-era institutions or the Baath decide who held power in Syria after 2011?"
Add-Content "$log/console.log" "=== ask start $(Get-Date -Format o) ==="
$start = Get-Date
"1" | uv run axial ask $question --case $case *>&1 | Add-Content "$log/console.log"
$rc = $LASTEXITCODE
$secs = [int]((Get-Date) - $start).TotalSeconds
Add-Content "$log/console.log" "--- exit=$rc seconds=$secs"
Add-Content "$log/run.jsonl" "{`"unit`":`"ask`",`"attempt`":2,`"exit`":$rc,`"seconds`":$secs}"
