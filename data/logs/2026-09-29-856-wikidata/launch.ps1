Set-Location D:/axial-runs
uv run --project D:/axial-856 axial names wikidata *> D:/axial-runs/data/logs/2026-09-29-856-wikidata/console-3.log
"exit=$LASTEXITCODE" | Out-File -Append D:/axial-runs/data/logs/2026-09-29-856-wikidata/console-3.log
