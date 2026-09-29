"""SplatFlow web server: upload a video, get a 3D Gaussian splat.

Run with the splatflow venv (baslat.ps1 does all of this for you):
    venv\\Scripts\\python.exe server.py
Expose with:
    cloudflared tunnel --url http://127.0.0.1:8088

Security model (safe to hand a trycloudflare link to friends):
  * Every request needs the access key. The link is  <url>/?k=<key>; the key is
    swapped for an HttpOnly/SameSite=Strict cookie and stripped from the URL.
    Key = env SPLATFLOW_TOKEN, or a random one printed at start-up.
  * Each browser gets its own anonymous id: people only see / download their
    own jobs. Nothing else under jobs/ (input videos, work dirs) is served.
  * Upload size, per-user rate and queue length are capped.
  * No API docs, strict security headers, server bound to 127.0.0.1 only.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


TOKEN = os.environ.get("SPLATFLOW_TOKEN", "").strip() or secrets.token_urlsafe(24)
AUTH = hmac.new(TOKEN.encode(), b"splatflow-auth", hashlib.sha256).hexdigest()
MAX_BYTES = _env_int("SPLATFLOW_MAX_MB", 3072) * 1024 * 1024
MAX_UPLOADS_PER_HOUR = _env_int("SPLATFLOW_UPLOADS_PER_HOUR", 10)
MAX_ACTIVE_PER_USER = _env_int("SPLATFLOW_ACTIVE_PER_USER", 2)
MAX_QUEUE = _env_int("SPLATFLOW_MAX_QUEUE", 8)
ALLOW_MANUAL = os.environ.get("SPLATFLOW_ALLOW_MANUAL", "1").strip() == "1"
COOKIE_AGE = 7 * 24 * 3600

app = FastAPI(title="SplatFlow", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

STATE: dict[str, dict] = {}
GPU_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
UPLOADS: dict[str, deque] = defaultdict(deque)
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".360", ".insv", ".lrv"}
MODES = {"standard", "full", "fast", "manual"}
JOB_RE = re.compile(r"[0-9a-f]{10}")
UID_RE = re.compile(r"[0-9a-f]{32}")
RESULT_FILES = {"splat.ply", "mesh.glb", "mesh.ply", "mesh.obj"}
PUBLIC_KEYS = ("state", "stage", "progress", "message", "last_log", "filename",
               "mode", "outputs", "n_frames", "created")

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob:; "
       "worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self' data: blob:; font-src 'self' data:; object-src 'none'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


# ---------------------------------------------------------------------------
# auth / hardening
# ---------------------------------------------------------------------------
def _harden(resp):
    h = resp.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    h.setdefault("Cache-Control", "no-store")
    return resp


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _uid(request: Request) -> str:
    return request.state.uid


LOCKED_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>SplatFlow</title><body style="margin:0;display:grid;place-items:center;height:100vh;background:#0b0c0f;
color:#e9e6df;font-family:system-ui,Segoe UI,sans-serif"><div style="text-align:center;max-width:360px;padding:24px">
<div style="font-size:13px;letter-spacing:.24em;color:#c8a96a">SPLATFLOW</div>
<h1 style="font-weight:500;font-size:22px">Erisim linki gerekli</h1>
<p style="color:#8c8a85;font-size:14px;line-height:1.6">Bu sayfaya yalnizca sahibinin paylastigi ozel linkle girilebilir.</p></div>"""


@app.middleware("http")
async def guard(request: Request, call_next):
    key = request.query_params.get("k")
    if key is not None:
        # login link: trade the key for a cookie and strip it from the URL
        if not hmac.compare_digest(key.encode(), TOKEN.encode()):
            await asyncio.sleep(0.5)
            return _harden(HTMLResponse(LOCKED_PAGE, status_code=401))
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("sf_auth", AUTH, max_age=COOKIE_AGE, httponly=True,
                        samesite="strict", secure=_is_https(request))
        if not UID_RE.fullmatch(request.cookies.get("sf_uid", "")):
            resp.set_cookie("sf_uid", uuid.uuid4().hex, max_age=365 * 24 * 3600,
                            httponly=True, samesite="strict", secure=_is_https(request))
        return _harden(resp)

    if not hmac.compare_digest(request.cookies.get("sf_auth", "").encode(), AUTH.encode()):
        if request.url.path.startswith("/api/"):
            return _harden(JSONResponse({"error": "unauthorized"}, status_code=401))
        return _harden(HTMLResponse(LOCKED_PAGE, status_code=401))

    uid = request.cookies.get("sf_uid", "")
    new_uid = not UID_RE.fullmatch(uid)
    if new_uid:
        uid = uuid.uuid4().hex
    request.state.uid = uid

    if request.url.path == "/api/upload":
        cl = request.headers.get("content-length")
        if cl is None or not cl.isdigit():
            return _harden(JSONResponse({"error": "Content-Length gerekli."}, status_code=411))
        if int(cl) > MAX_BYTES:
            return _harden(JSONResponse(
                {"error": f"Dosya cok buyuk (en fazla {MAX_BYTES // (1024 * 1024)} MB)."},
                status_code=413))

    resp = await call_next(request)
    if new_uid:
        resp.set_cookie("sf_uid", uid, max_age=365 * 24 * 3600, httponly=True,
                        samesite="strict", secure=_is_https(request))
    return _harden(resp)


# ---------------------------------------------------------------------------
# job bookkeeping (meta.json lets finished jobs survive a restart)
# ---------------------------------------------------------------------------
def _write_meta(job_dir: Path, meta: dict) -> None:
    (job_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _outputs(job_dir: Path) -> dict | None:
    res = job_dir / "result"
    if not (res / "splat.ply").is_file():
        return None
    out = {"splat": f"/files/{job_dir.name}/result/splat.ply"}
    for ext in ("glb", "ply", "obj"):
        if (res / f"mesh.{ext}").is_file():
            out[ext] = f"/files/{job_dir.name}/result/mesh.{ext}"
    return out


def _restore_jobs() -> None:
    for d in JOBS.iterdir() if JOBS.is_dir() else []:
        meta_f = d / "meta.json"
        if not (d.is_dir() and JOB_RE.fullmatch(d.name) and meta_f.is_file()):
            continue
        try:
            meta = json.loads(meta_f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        out = _outputs(d)
        STATE[d.name] = {
            **meta, "state": "done" if out else "error", "stage": "done" if out else "error",
            "progress": 100 if out else 0, "outputs": out, "last_log": "", "log": "",
            "message": "Tamamlandi." if out else "Sunucu yeniden basladi, is yarida kaldi.",
        }


_restore_jobs()


def _redact(text) -> str:
    s = str(text or "")
    for p in (str(JOBS), str(HERE), str(Path.home()), str(pipeline.SPIRULA.parent)):
        if p and len(p) > 3:
            s = s.replace(p, "…")
    return s[-600:]


def _public(st: dict) -> dict:
    out = {k: st.get(k) for k in PUBLIC_KEYS}
    out["message"] = _redact(out["message"])
    out["last_log"] = _redact(out["last_log"])
    return out


def _worker(job_id: str, video: Path, opts: dict) -> None:
    state = STATE[job_id]
    with GPU_LOCK:
        pipeline.run_pipeline(JOBS / job_id, video, state, opts)


def _rate_ok(uid: str) -> bool:
    now = time.time()
    q = UPLOADS[uid]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= MAX_UPLOADS_PER_HOUR:
        return False
    q.append(now)
    return True


async def _save(upload: UploadFile, dest: Path) -> bool:
    """Copy the upload, refusing anything past MAX_BYTES."""
    total = 0
    with dest.open("wb") as out:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_BYTES:
                break
            out.write(chunk)
    if total > MAX_BYTES or total == 0:
        dest.unlink(missing_ok=True)
        return False
    return True


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((HERE / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/viewer", response_class=HTMLResponse)
def viewer() -> HTMLResponse:
    return HTMLResponse((HERE / "static" / "viewer.html").read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/api/config")
def config() -> JSONResponse:
    return JSONResponse({"max_mb": MAX_BYTES // (1024 * 1024), "manual": ALLOW_MANUAL,
                         "busy": GPU_LOCK.locked()})


@app.post("/api/upload")
async def upload(request: Request, video: UploadFile = File(...),
                 mode: str = Form("standard")) -> JSONResponse:
    uid = _uid(request)
    if mode not in MODES:
        return JSONResponse({"error": "Gecersiz mod."}, status_code=400)
    if mode == "manual" and not ALLOW_MANUAL:
        return JSONResponse({"error": "Manuel mod kapali."}, status_code=403)
    ext = Path(video.filename or "input.mp4").suffix.lower()
    if ext not in VIDEO_EXT:
        return JSONResponse({"error": "Desteklenmeyen dosya turu."}, status_code=415)
    with STATE_LOCK:
        active = [s for s in STATE.values() if s["state"] == "running"]
        if mode != "manual" and sum(s.get("owner") == uid for s in active) >= MAX_ACTIVE_PER_USER:
            return JSONResponse({"error": "Zaten suren islerin var, bitmesini bekle."}, status_code=429)
        if mode != "manual" and len(active) >= MAX_QUEUE:
            return JSONResponse({"error": "Kuyruk dolu, biraz sonra tekrar dene."}, status_code=429)
        if not _rate_ok(uid):
            return JSONResponse({"error": "Saatlik yukleme siniri doldu."}, status_code=429)
    filename = Path(video.filename or "video").name[:120]

    # Option 2: just save the file to the PC and open Studio, process by hand.
    if mode == "manual":
        stamp = time.strftime("%Y%m%d_%H%M%S")
        # short name on purpose: Studio appends "_dataset_N/outputs/<name>_<time>/",
        # and the full original name blows past Windows' 260-char path limit.
        dest = INCOMING / f"v_{stamp}_{secrets.token_hex(2)}{ext}"
        if not await _save(video, dest):
            return JSONResponse({"error": "Dosya bos ya da cok buyuk."}, status_code=413)
        launched = False
        if OPEN_STUDIO:
            try:
                subprocess.Popen([str(pipeline.SPIRULA), str(dest)], close_fds=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                launched = True
            except Exception:  # noqa: BLE001
                launched = False
        return JSONResponse({"mode": "manual", "saved": dest.name, "studio": launched})

    # Option 1: run the automated pipeline.
    job_id = uuid.uuid4().hex[:10]
    job_dir = JOBS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    dest = job_dir / f"input{ext}"
    if not await _save(video, dest):
        shutil.rmtree(job_dir, ignore_errors=True)
        return JSONResponse({"error": "Dosya bos ya da cok buyuk."}, status_code=413)

    meta = {"owner": uid, "filename": filename, "mode": mode, "created": int(time.time())}
    _write_meta(job_dir, meta)
    opts = pipeline.MODES.get(mode, {})
    STATE[job_id] = {
        **meta, "state": "running", "stage": "queued", "progress": 1,
        "message": "Kuyruga alindi...", "last_log": "", "log": "", "outputs": None,
    }
    threading.Thread(target=_worker, args=(job_id, dest, opts), daemon=True).start()
    return JSONResponse({"mode": "auto", "job_id": job_id})


@app.get("/api/status/{job_id}")
def status(request: Request, job_id: str) -> JSONResponse:
    st = STATE.get(job_id)
    if st is None or st.get("owner") != _uid(request):
        return JSONResponse({"state": "unknown"}, status_code=404)
    return JSONResponse(jsonable_encoder(_public(st)))


@app.get("/api/jobs")
def jobs(request: Request) -> JSONResponse:
    uid = _uid(request)
    mine = [(jid, st) for jid, st in STATE.items() if st.get("owner") == uid]
    mine.sort(key=lambda x: x[1].get("created") or 0, reverse=True)
    return JSONResponse(jsonable_encoder([{"id": jid, **_public(st)} for jid, st in mine[:30]]))


@app.get("/files/{job_id}/result/{name}")
def files(request: Request, job_id: str, name: str):
    st = STATE.get(job_id)
    if (not JOB_RE.fullmatch(job_id) or name not in RESULT_FILES or st is None
            or st.get("owner") != _uid(request)):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = JOBS / job_id / "result" / name
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="application/octet-stream")


if __name__ == "__main__":
    import uvicorn

    if not os.environ.get("SPLATFLOW_TOKEN"):
        print(f"\n  Erisim linki:  http://127.0.0.1:8088/?k={TOKEN}\n"
              f"  (tunel adresinin sonuna da  /?k={TOKEN}  ekleyin)\n")
    uvicorn.run(app, host="127.0.0.1", port=8088, log_level="info",
                server_header=False, proxy_headers=False)
