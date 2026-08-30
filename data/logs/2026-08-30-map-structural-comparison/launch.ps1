Set-Location D:\axial
$env:AXIAL_SECRETS_PATH = 'secrets/secrets.toml'
$env:PYTHONUNBUFFERED = '1'
$log = 'D:\axial\data\logs\2026-08-30-map-structural-comparison\console.log'
"=== replicate launched $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8
uv run axial map build --grouping category --force *>&1 | ForEach-Object {
    $_ | Out-File -FilePath $log -Append -Encoding utf8
}
"=== replicate exited $LASTEXITCODE at $(Get-Date -Format o) ===" | Out-File -FilePath $log -Append -Encoding utf8
