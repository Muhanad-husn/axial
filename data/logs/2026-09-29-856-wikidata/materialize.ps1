Set-Location D:/axial-runs
uv run axial names materialize *> D:/axial-runs/data/logs/2026-09-29-856-wikidata/materialize.log
"exit=$LASTEXITCODE" | Out-File -Append D:/axial-runs/data/logs/2026-09-29-856-wikidata/materialize.log
