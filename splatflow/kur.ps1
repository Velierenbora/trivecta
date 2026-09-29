# SplatFlow - tek seferlik kurulum (tak-calistir)
# Kullanim:  powershell -ExecutionPolicy Bypass -File .\kur.ps1
# Yapar: Python venv + paketler, ffmpeg, cloudflared, trivecta.exe (hazir surum ya da derleme).
# Sonra:   powershell -ExecutionPolicy Bypass -File .\baslat.ps1

$ErrorActionPreference = "Stop"
$wd   = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $wd
Set-Location $wd

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function WingetInstall($id) {
    if (-not (Have winget)) { Write-Host "  winget yok; '$id' paketini elle kur." -ForegroundColor Yellow; return }
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent
}

Write-Host "[1/5] GPU kontrolu"
if (Have nvidia-smi) { nvidia-smi --query-gpu=name,compute_cap,driver_version --format=csv,noheader }
else { Write-Host "  NVIDIA surucusu bulunamadi. CUDA surumu icin guncel NVIDIA surucusu gerekir." -ForegroundColor Yellow }

Write-Host "[2/5] Python ortami"
if (-not (Test-Path "$wd\venv\Scripts\python.exe")) {
    if (Have py) { py -3 -m venv venv } elseif (Have python) { python -m venv venv }
    else { WingetInstall "Python.Python.3.12"; throw "Python kuruldu; yeni bir PowerShell acip kur.ps1'i tekrar calistir." }
}
& "$wd\venv\Scripts\python.exe" -m pip install --upgrade pip -q
& "$wd\venv\Scripts\python.exe" -m pip install -r "$wd\requirements.txt" -q

Write-Host "[3/5] ffmpeg"
$ff = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\*FFmpeg*\*\bin\ffmpeg.exe" -ErrorAction SilentlyContinue
if (-not (Have ffmpeg) -and -not $ff -and -not $env:FFMPEG_EXE) { WingetInstall "Gyan.FFmpeg" } else { Write-Host "  tamam" }

Write-Host "[4/5] cloudflared"
if (-not (Have cloudflared) -and -not (Test-Path "C:\Program Files (x86)\cloudflared\cloudflared.exe")) {
    WingetInstall "Cloudflare.cloudflared"
} else { Write-Host "  tamam" }

Write-Host "[5/5] Trivecta motoru"
$exe = @($env:SPIRULA_EXE, "C:\trivecta\trivecta.exe", "$repo\bin\trivecta.exe", "$repo\trivecta\build\trivecta.exe") |
       Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($exe) { Write-Host "  bulundu: $exe" }
else {
    # hazir, tum RTX kartlari icin derlenmis surum (GitHub Releases: trivecta-win64.zip)
    $zip = "$env:TEMP\trivecta-win64.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $rel = Invoke-RestMethod "https://api.github.com/repos/Velierenbora/trivecta/releases/latest" -Headers @{ "User-Agent" = "splatflow" }
        $asset = $rel.assets | Where-Object { $_.name -eq "trivecta-win64.zip" } | Select-Object -First 1
        if (-not $asset) { throw "release'te trivecta-win64.zip yok" }
        Invoke-WebRequest $asset.browser_download_url -OutFile $zip -UseBasicParsing
        Expand-Archive $zip -DestinationPath "$repo\bin" -Force
        Write-Host "  indirildi: $repo\bin\trivecta.exe"
    } catch {
        Write-Host "  Hazir surum indirilemedi ($($_.Exception.Message))." -ForegroundColor Yellow
        Write-Host "  Kaynaktan derle (GPU'n otomatik algilanir):"
        Write-Host "    powershell -ExecutionPolicy Bypass -File $repo\scripts\build-trivecta.ps1"
    }
}

Write-Host ""
Write-Host "Kurulum bitti. Baslatmak icin:  powershell -ExecutionPolicy Bypass -File .\baslat.ps1" -ForegroundColor Green
