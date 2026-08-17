# #784 slice 01 pre-measurement, PowerShell edition.
# The Bash tool exports AXIAL_SECRETS_PATH=/secrets/secrets.toml (a POSIX path
# MSYS mangles out of the repo-relative default), which resolves to nothing on
# Windows and made every run fail with LLMConfigError before any model call.
# Cleared here.
$env:AXIAL_SECRETS_PATH = $null
$log = "data/logs/2026-08-17-784-question-as-thesis"
Set-Content -Path "$log/console.log" -Value "" -NoNewline
Set-Content -Path "$log/run.jsonl" -Value "" -NoNewline
foreach ($f in Get-ChildItem "$log/briefs/*.yaml") {
  $id = $f.BaseName
  $start = Get-Date
  Add-Content "$log/console.log" "=== $id ==="
  uv run axial paper examine $f.FullName *>&1 | Add-Content "$log/console.log"
  $rc = $LASTEXITCODE
  $secs = [int]((Get-Date) - $start).TotalSeconds
  Add-Content "$log/run.jsonl" "{`"analysis_id`":`"$id`",`"exit`":$rc,`"seconds`":$secs}"
  Add-Content "$log/console.log" "--- exit=$rc seconds=$secs"
}
Add-Content "$log/console.log" "DONE"
