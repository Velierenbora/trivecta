# Builds Trivecta (the GUI) from this repository's source on Windows.
# Requirements: Visual Studio 2022 (C++ workload), CMake + Ninja, CUDA Toolkit 12.8+.
# Run from a PowerShell prompt:  powershell -ExecutionPolicy Bypass -File .\scripts\build-trivecta.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$src  = Join-Path $root "trivecta"

$cuda = $env:CUDA_PATH
if (-not $cuda) { $cuda = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8" }
if (-not (Test-Path $cuda)) { throw "CUDA toolkit not found. Set CUDA_PATH." }

# Default = "universal": one exe that runs on every RTX card without recompiling
# (7.5 RTX 20xx/GTX 16xx, 8.6 RTX 30xx, 8.9 RTX 40xx, 12.0 RTX 50xx).
# Faster single-GPU build:  $env:TORCH_CUDA_ARCH_LIST = "12.0"
$arch = if ($env:TORCH_CUDA_ARCH_LIST) { $env:TORCH_CUDA_ARCH_LIST } else { "7.5;8.6;8.9;12.0" }
$backend = if ($env:SS_BACKEND) { $env:SS_BACKEND } else { "cuda" }   # or "vulkan"

Set-Location $src
cmake -G Ninja -B build -DSS_BACKEND=$backend -DSS_NO_TORCH=ON -DCMAKE_BUILD_TYPE=Release `
      -DCUDAToolkit_ROOT="$cuda" "-DTORCH_CUDA_ARCH_LIST=$arch"
cmake --build build --target spirula

$exe = Join-Path $src "build\trivecta.exe"
if (-not (Test-Path $exe)) { throw "Build finished but trivecta.exe was not found." }
Write-Host "Built: $exe"

# Package a drop-in bundle (exe + DLLs incl. the CUDA runtime) for friends / GitHub Releases.
# Upload dist\trivecta-win64.zip to a release and splatflow\kur.ps1 downloads it automatically.
$dist = Join-Path $root "dist"; $stage = Join-Path $dist "trivecta"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $stage -Force | Out-Null
Copy-Item $exe $stage
Get-ChildItem (Join-Path $src "build") -Filter *.dll -ErrorAction SilentlyContinue | Copy-Item -Destination $stage
Get-ChildItem (Join-Path $cuda "bin") -Filter "cudart64_*.dll" -ErrorAction SilentlyContinue | Copy-Item -Destination $stage
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath (Join-Path $dist "trivecta-win64.zip") -Force
Write-Host "Bundle: $(Join-Path $dist 'trivecta-win64.zip')"
