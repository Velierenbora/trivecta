# SplatFlow - baslat / yeniden baslat
# Kullanim:  powershell -ExecutionPolicy Bypass -File .\baslat.ps1
# Yeni bir trycloudflare URL'si uretir ve ekrana yazar.

$ErrorActionPreference = "SilentlyContinue"
$wd = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $wd
$cf = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

Write-Host "Eski surecler durduruluyor..."
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*splatflow\venv\Scripts\python.exe" } |
    Stop-Process -Force
Start-Sleep -Seconds 2

Write-Host "SplatFlow sunucusu baslatiliyor (127.0.0.1:8088)..."
Start-Process -FilePath "$wd\venv\Scripts\python.exe" -ArgumentList "server.py" `
    -WorkingDirectory $wd -WindowStyle Hidden `
    -RedirectStandardOutput "$wd\server.out.log" `
    -RedirectStandardError  "$wd\server.err.log"
Start-Sleep -Seconds 8

Write-Host "Cloudflare tunnel baslatiliyor..."
Start-Process -FilePath $cf -ArgumentList "tunnel", "--url", "http://127.0.0.1:8088", "--no-autoupdate" `
    -WorkingDirectory $wd -WindowStyle Hidden `
    -RedirectStandardOutput "$wd\cloudflared.log" `
    -RedirectStandardError  "$wd\cloudflared.err.log"
Start-Sleep -Seconds 25

$url = (Select-String -Path "$wd\cloudflared.log", "$wd\cloudflared.err.log" `
        -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" |
        ForEach-Object { $_.Matches[0].Value } | Select-Object -First 1)
$url | Set-Content "$wd\TUNNEL_URL.txt"
Write-Host ""
Write-Host "=================================================="
Write-Host "  HAZIR!  Tarayicida ac:  $url"
Write-Host "=================================================="
