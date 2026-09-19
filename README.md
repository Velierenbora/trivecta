# Trivecta — Video → 3D Gaussian Splatting

**Trivecta** turns ordinary video into an explorable 3D Gaussian Splat. It is a
single-binary, GPU-accelerated reconstruction studio (Vulkan/CUDA, no Python or
COLMAP required) plus **SplatFlow**, a small web front-end that accepts a video
upload over a Cloudflare Tunnel and drives the whole pipeline automatically.

> Status: MVP. Tested on **NVIDIA RTX 5070 (Blackwell, sm_120)** + Windows 11.

---

## What it does

```
video / photos
      │
      ▼
  frame extraction (motion-aware)  ── picks sharp, well-spaced frames
      │
      ▼
  SfM  (structure from motion, GPU)  ── camera poses + sparse points
      │
      ▼
  3D Gaussian Splatting training  ── .ply splat  (+ optional textured mesh .glb)
      │
      ▼
  interactive viewer  ── orbit the room in real time
```

- **Motion-aware frame selection** — frames are spaced by how much the *view*
  changed (`cost = coverage + 2 × parallax`), not by fixed time steps, so a
  shaky or fast clip still reconstructs cleanly.
- **Per-photo exposure / white-balance correction** and **floater suppression**
  for phone footage.
- **Real-time native viewer** and a **standalone web viewer** (Gaussian splats).
- **Mesh extraction** (`.glb` / `.obj` / `.ply`) for surfaces and floorplans.

## Components

| Path | What it is |
|---|---|
| `trivecta/` | **Trivecta** — the native reconstruction studio (C++ / Dear ImGui, CUDA or Vulkan backend). A rebranded, restyled build of [Spirula Studio](https://github.com/harry7557558/spirula-studio). |
| `splatflow/` | **SplatFlow** — FastAPI web front-end: upload a video, run the pipeline, view the result. Includes the adaptive frame extractor. |

## Quick start

### 1. Trivecta (the desktop app)
Download `trivecta.exe` from the [Releases](../../releases) page and run it.
The home screen offers:

- **New Dataset** — pick a video or photo folder, choose a preset, extract
  frames (motion-aware), then **Start Training**.
- **Open 3D** — open a finished `.ply` splat in the viewer.
- **Train / Mesh / Batch** — everything the studio can do.

Requirements: Windows 10/11 x64, an NVIDIA GPU (RTX 20-series or newer), a
recent driver. No CUDA toolkit or Python needed to *run* the prebuilt binary.

### 2. SplatFlow (the web front-end)
```powershell
cd splatflow
python -m venv venv
.\venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" python-multipart numpy opencv-python-headless pillow
.\venv\Scripts\python.exe server.py          # http://127.0.0.1:8088
```
Expose it publicly with a free quick tunnel:
```powershell
cloudflared tunnel --url http://127.0.0.1:8088
```
The upload page offers two options:

1. **Process on the web** — upload → adaptive frames → SfM → train → the model
   opens in Trivecta.
2. **Save to PC** — the video is saved to `C:\splat\` and Trivecta opens with
   it, for manual processing.

`SplatFlow` calls `trivecta.exe`; set `SPIRULA_EXE` if it lives elsewhere.

## Build Trivecta from source (Windows)

Prerequisites: Visual Studio 2022 (C++ workload), CMake + Ninja, and the
**CUDA Toolkit 12.8+** (or the Vulkan SDK for the Vulkan backend).

```powershell
# from a developer prompt with cmake/ninja on PATH
cmake -G Ninja -B build -DSS_BACKEND=cuda -DSS_NO_TORCH=ON -DCMAKE_BUILD_TYPE=Release ^
      -DCUDAToolkit_ROOT="C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8" ^
      -DTORCH_CUDA_ARCH_LIST=12.0
cmake --build build --target spirula      # produces build\trivecta.exe
```

`TORCH_CUDA_ARCH_LIST` selects the GPU architecture (`12.0` = Blackwell/sm_120,
`8.6` = Ampere, etc.). For AMD/Intel/Apple use `-DSS_BACKEND=vulkan`.

## License & credits

- **Trivecta** is a modified build of **Spirula Studio** by harry7557558
  (<https://github.com/harry7557558/spirula-studio>), and is distributed under
  the **GNU GPL-3.0** (see `trivecta/LICENSE`). Modifications: product name and
  window title, light theme, larger UI font, a welcome headline, and an
  "Open 3D" entry point.
- **SplatFlow** (this repository's `splatflow/`) is released under the **MIT
  License** (see `splatflow/LICENSE`).
- Bundled fonts (Source Sans, Noto Sans CJK subsets) keep their own OFL
  licenses; see `trivecta/assets/fonts/`.
- AI model weights (e.g. SAM for masking, ALIKED/LightGlue features) are **not**
  bundled; the application downloads them on demand under their own licenses.

## Security

See [`SECURITY.md`](SECURITY.md). Short version: no credentials are stored in
this repository, the web front-end binds to localhost, and you should add
authentication before exposing it to the internet.

## Türkçe özet

**Trivecta**, videodan gerçek zamanlı gezilebilir 3B Gaussian Splat üreten tek
dosyalık bir Windows uygulamasıdır (Spirula Studio'nun yeniden markalanmış ve
beyaz temalı sürümü). **SplatFlow** ise bir videoyu tarayıcıdan (Cloudflare
Tunnel üzerinden) yükleyip tüm işlem hattını otomatik çalıştıran küçük bir web
arayüzüdür. Kurulum ve kullanım yukarıdaki adımlardadır.
