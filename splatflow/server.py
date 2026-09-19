"""SplatFlow web server: upload a video, get a 3D Gaussian splat.

Run with the splatflow venv:
    venv\\Scripts\\python.exe server.py
Expose with:
    cloudflared tunnel --url http://127.0.0.1:8088
"""
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import pipeline

HERE = Path(__file__).resolve().parent
JOBS = pipeline.JOBS
JOBS.mkdir(parents=True, exist_ok=True)
# Short base path on purpose: Studio appends "_dataset_N/outputs/<name>_<time>/...",
# and a deep base + long name blows past Windows' 260-char path limit.
INCOMING = Path(os.environ.get("SS_INCOMING", r"C:\splat"))
INCOMING.mkdir(parents=True, exist_ok=True)
OPEN_STUDIO = pipeline.defaults()["open_studio"] == "1"

app = FastAPI(title="SplatFlow")
app.mount("/files", StaticFiles(directory=str(JOBS)), name="files")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

STATE: dict[str, dict] = {}
GPU_LOCK = threading.Lock()
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".360", ".insv", ".lrv"}


def _worker(job_id: str, video: Path, opts: dict) -> None:
    state = STATE[job_id]
    with GPU_LOCK:
        pipeline.run_pipeline(JOBS / job_id, video, state, opts)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((HERE / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "jobs": len(STATE)})


@app.post("/api/upload")
async def upload(video: UploadFile = File(...), mode: str = Form("standard")) -> JSONResponse:
    ext = Path(video.filename or "input.mp4").suffix.lower()
    if ext not in VIDEO_EXT:
        ext = ".mp4"

    # Option 2: just save the file to the PC and open Studio, process by hand.
    if mode == "manual":
        stamp = time.strftime("%Y%m%d_%H%M%S")
        # short name on purpose: Studio appends "_dataset_N/outputs/<name>_<time>/",
        # and the full original name blows past Windows' 260-char path limit.
        dest = INCOMING / f"v_{stamp}{ext}"
        with dest.open("wb") as out:
            shutil.copyfileobj(video.file, out, length=1024 * 1024)
        launched = False
        if OPEN_STUDIO:
            try:
                subprocess.Popen([str(pipeline.SPIRULA), str(dest)], close_fds=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                launched = True
            except Exception:  # noqa: BLE001
                launched = False
        return JSONResponse({"mode": "manual", "saved": str(dest),
                             "folder": str(INCOMING), "studio": launched})

    # Option 1: run the automated pipeline.
    job_id = uuid.uuid4().hex[:10]
    job_dir = JOBS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    dest = job_dir / f"input{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(video.file, out, length=1024 * 1024)

    opts = pipeline.MODES.get(mode, {})
    STATE[job_id] = {
        "state": "running", "stage": "queued", "progress": 1,
        "message": "Kuyruga alindi...", "last_log": "", "log": "",
        "filename": video.filename, "mode": mode, "outputs": None,
    }
    threading.Thread(target=_worker, args=(job_id, dest, opts), daemon=True).start()
    return JSONResponse({"mode": "auto", "job_id": job_id})


@app.get("/api/status/{job_id}")
def status(job_id: str) -> JSONResponse:
    st = STATE.get(job_id)
    if st is None:
        return JSONResponse({"state": "unknown"}, status_code=404)
    return JSONResponse(jsonable_encoder(st))


@app.get("/api/jobs")
def jobs() -> JSONResponse:
    return JSONResponse([
        {"id": jid, "state": st["state"], "progress": st["progress"],
         "message": st["message"]}
        for jid, st in STATE.items()
    ])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8088, log_level="info")
