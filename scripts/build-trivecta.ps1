# Builds Trivecta (the GUI) from this repository's source on Windows.
# Requirements: Visual Studio 2022 (C++ workload), CMake + Ninja, CUDA Toolkit 12.8+.
# Run from a PowerShell prompt:  powershell -ExecutionPolicy Bypass -File .\scripts\build-trivecta.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$src  = Join-Path $root "trivecta"

$cuda = $env:CUDA_PATH
if (-not $cuda) { $cuda = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8" }
if (-not (Test-Path $cuda)) { throw "CUDA toolkit not found. Set CUDA_PATH." }

$arch = if ($env:TORCH_CUDA_ARCH_LIST) { $env:TORCH_CUDA_ARCH_LIST } else { "12.0" }
$backend = if ($env:SS_BACKEND) { $env:SS_BACKEND } else { "cuda" }   # or "vulkan"

Set-Location $src
cmake -G Ninja -B build -DSS_BACKEND=$backend -DSS_NO_TORCH=ON -DCMAKE_BUILD_TYPE=Release `
      -DCUDAToolkit_ROOT="$cuda" -DTORCH_CUDA_ARCH_LIST=$arch
cmake --build build --target spirula

$exe = Join-Path $src "build\trivecta.exe"
if (Test-Path $exe) { Write-Host "Built: $exe" } else { throw "Build finished but trivecta.exe was not found." }
