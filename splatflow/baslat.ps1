# SplatFlow - baslat / yeniden baslat
# Kullanim:  powershell -ExecutionPolicy Bypass -File .\baslat.ps1
# Yeni bir trycloudflare URL'si + her calistirmada YENI bir gizli erisim anahtari uretir.
# Sadece ekrana yazilan TAM linki paylas; anahtarsiz adres hicbir sey gostermez.

$ErrorActionPreference = "Continue"
$wd = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $wd
$pidFile = "$wd\.splatflow.pids"

$py = "$wd\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "venv yok. Once kurulum:  powershell -ExecutionPolicy Bypass -File .\kur.ps1" -ForegroundColor Yellow; exit 1 }

$cf = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
if (-not (Test-Path $cf)) { $c = Get-Command cloudflared -ErrorAction SilentlyContinue; if ($c) { $cf = $c.Source } }
if (-not (Test-Path $cf)) { Write-Host "cloudflared bulunamadi. kur.ps1 calistir." -ForegroundColor Yellow; exit 1 }

Write-Host "Eski SplatFlow surecleri durduruluyor..."
# yalnizca bizim baslattigimiz surecler (baska cloudflared tunellerine dokunma)
if (Test-Path $pidFile) {
    Get-Content $pidFile | ForEach-Object { Stop-Process -Id ([int]$_) -Force -ErrorAction SilentlyContinue }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*splatflow\venv\Scripts\python.exe" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# kriptografik rastgele erisim anahtari
$bytes = New-Object byte[] 24
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$token = ([BitConverter]::ToString($bytes) -replace '-', '').ToLower()
$env:SPLATFLOW_TOKEN = $token

Remove-Item "$wd\cloudflared.log", "$wd\cloudflared.err.log" -ErrorAction SilentlyContinue

Write-Host "SplatFlow sunucusu baslatiliyor (127.0.0.1:8088)..."
$srv = Start-Process -FilePath $py -ArgumentList "server.py" -PassThru `
    -WorkingDirectory $wd -WindowStyle Hidden `
    -RedirectStandardOutput "$wd\server.out.log" `
    -RedirectStandardError  "$wd\server.err.log"
Start-Sleep -Seconds 6

Write-Host "Cloudflare tunnel baslatiliyor..."
$tun = Start-Process -FilePath $cf -ArgumentList "tunnel", "--url", "http://127.0.0.1:8088", "--no-autoupdate" -PassThru `
    -WorkingDirectory $wd -WindowStyle Hidden `
    -RedirectStandardOutput "$wd\cloudflared.log" `
    -RedirectStandardError  "$wd\cloudflared.err.log"
@($srv.Id, $tun.Id) | Set-Content $pidFile

$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    Start-Sleep -Seconds 2
    $url = (Select-String -Path "$wd\cloudflared.log", "$wd\cloudflared.err.log" -ErrorAction SilentlyContinue `
            -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" |
            ForEach-Object { $_.Matches[0].Value } | Select-Object -First 1)
}
$share = "$url/?k=$token"
$share | Set-Content "$wd\TUNNEL_URL.txt"
Write-Host ""
Write-Host "=================================================="
Write-Host "  HAZIR!  Paylasilacak link (anahtar dahil):"
Write-Host "  $share" -ForegroundColor Green
Write-Host ""
Write-Host "  Bu PC'den:  http://127.0.0.1:8088/?k=$token"
Write-Host "  Linki sadece guvendigin kisilerle paylas. Yeniden"
Write-Host "  baslatinca eski link gecersiz olur."
Write-Host "=================================================="
