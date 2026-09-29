"""Video -> 3D Gaussian Splat pipeline built on Spirula Studio.

Stages:
  1. ffmpeg normalise (H.264, <=1920px)             -> work/input.mp4
  2. spirula sam extract                            -> work/frames/
  3. spirula sfm auto                               -> work/sfm/sparse/0
  4. dataset layout (images/ + sparse/)             -> work/dataset/
  5. spirula train 3dgs                             -> runs/run/step-*.ckpt/splat.ply
  6. (optional) spirula mesh                        -> result/mesh.glb
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def _first_existing(*cands) -> Path | None:
    for c in cands:
        if c and Path(c).is_file():
            return Path(c)
    return None


def _find_spirula() -> Path:
    """env SPIRULA_EXE > C:\\trivecta > repo bin/ (kur.ps1) > local build."""
    if os.environ.get("SPIRULA_EXE"):
        return Path(os.environ["SPIRULA_EXE"])
    return _first_existing(
        r"C:\trivecta\trivecta.exe",
        REPO / "bin" / "trivecta.exe",
        REPO / "trivecta" / "build" / "trivecta.exe",
    ) or Path(r"C:\trivecta\trivecta.exe")


def _find_ffmpeg() -> Path:
    """env FFMPEG_EXE > PATH > any WinGet ffmpeg install > plain 'ffmpeg'."""
    if os.environ.get("FFMPEG_EXE"):
        return Path(os.environ["FFMPEG_EXE"])
    hit = shutil.which("ffmpeg")
    if hit:
        return Path(hit)
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    winget = local / "Microsoft" / "WinGet"
    found = _first_existing(winget / "Links" / "ffmpeg.exe",
                            *sorted((winget / "Packages").glob("*FFmpeg*/*/bin/ffmpeg.exe"),
                                    reverse=True))
    return found or Path("ffmpeg")


SPIRULA = _find_spirula()
FFMPEG = _find_ffmpeg()
JOBS = ROOT / "jobs"


def defaults() -> dict:
    return {
        "skip": os.environ.get("SS_EXTRACT_SKIP", "4").strip(),       # 1 = every frame
        "keep": os.environ.get("SS_EXTRACT_KEEP", "4").strip(),       # sharper frame pick
        "max_frames": os.environ.get("SS_MAX_FRAMES", "0").strip(),   # 0 = all of them
        "iters": os.environ.get("SS_ITERS", "10000").strip(),
        "quality": os.environ.get("SS_QUALITY", "medium").strip(),
        "res_divisor": os.environ.get("SS_RES_DIVISOR", "0").strip(),
        "mesh": os.environ.get("SS_MESH", "0").strip() == "1",
        "max_edge": os.environ.get("SS_MAX_EDGE", "1920").strip(),
        # video quality knobs
        "floater": os.environ.get("SS_FLOATER", "mild").strip(),      # off|mild|strong
        "erank": os.environ.get("SS_ERANK", "0.05").strip(),          # fewer needle splats
        "exif_exposure": os.environ.get("SS_EXIF_EXPOSURE", "1").strip(),
        "depth_reg": os.environ.get("SS_DEPTH_REG", "0").strip(),     # >0 helps fog on hard captures
        "rgb_reg": os.environ.get("SS_RGB_REG", "0").strip(),
        "distraction": os.environ.get("SS_DISTRACTION", "off").strip(),
        "extra": os.environ.get("SS_TRAIN_EXTRA", "").strip(),        # raw extra flags
        # motion-aware frame selection (port of Spirula's FrameMotion)
        "adaptive": os.environ.get("SS_ADAPTIVE", "1").strip(),
        "target": os.environ.get("SS_TARGET", "350").strip(),
        "cand_fps": os.environ.get("SS_CAND_FPS", "10").strip(),
        "open_studio": os.environ.get("SS_OPEN_STUDIO", "1").strip(),
    }


MODES = {
    # covers the whole video (skip=1 => every source frame)
    "full": {"skip": "1", "max_frames": "0", "iters": "20000", "quality": "high",
             "target": "700"},
    # default: whole timeline, subsampled
    "standard": {},
    # quick preview
    "fast": {"skip": "6", "max_frames": "250", "iters": "5000", "quality": "low",
             "floater": "off", "erank": "0", "target": "200"},
}


def _norm(p) -> str:
    return str(p)


def _run(cmd: list[str], state: dict, stage: str, pct: int, message: str,
         pct_end: int | None = None, progress_re: re.Pattern | None = None,
         progress_total: int | None = None) -> int:
    state.update(stage=stage, progress=pct, message=message)
    env = dict(os.environ)
    env["SS_LANG"] = "en"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env, bufsize=1,
    )
    buf: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\r\n")
        if not line:
            continue
        buf.append(line)
        if len(buf) > 120:
            buf.pop(0)
        state["last_log"] = line
        state["log"] = "\n".join(buf[-40:])
        if progress_re and pct_end and progress_total:
            m = progress_re.search(line)
            if m:
                frac = min(1.0, int(m.group(1)) / max(1, progress_total))
                state["progress"] = int(pct + (pct_end - pct) * frac)
    proc.wait()
    return proc.returncode


def _junction(link: Path, target: Path) -> None:
    if link.exists() or link.is_symlink():
        try:
            link.unlink()
        except OSError:
            shutil.rmtree(link, ignore_errors=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", _norm(link), _norm(target)],
                   capture_output=True, text=True)


def find_splat(runs: Path) -> Path | None:
    cands = list(runs.glob("*/step-*.ckpt/splat.ply")) + list(runs.glob("*/splat.ply"))
    if not cands:
        return None

    def step(p: Path) -> int:
        m = re.search(r"step-(\d+)", str(p))
        return int(m.group(1)) if m else -1

    return max(cands, key=step)


def run_pipeline(job_dir: Path, video: Path, state: dict, opts: dict | None = None) -> None:
    o = defaults()
    if opts:
        o.update({k: v for k, v in opts.items() if v is not None})
    work = job_dir / "work"
    result = job_dir / "result"
    work.mkdir(parents=True, exist_ok=True)
    result.mkdir(parents=True, exist_ok=True)
    try:
        # 1) normalise video -------------------------------------------------
        norm = work / "input.mp4"
        rc = _run([
            _norm(FFMPEG), "-y", "-loglevel", "error", "-i", _norm(video),
            "-vf", f"scale='min({o['max_edge']},iw)':-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-an", _norm(norm),
        ], state, "video", 4, "Video H.264'e normalize ediliyor (tum video)...")
        if rc != 0 or not norm.exists():
            raise RuntimeError("ffmpeg normalization failed")

        # 2) extract frames (whole timeline unless capped) -------------------
        frames = work / "frames"
        if o["adaptive"] == "1":
            rc = _run([
                sys.executable, str(ROOT / "adaptive_extract.py"),
                "--ffmpeg", _norm(FFMPEG), "--video", _norm(norm),
                "--out", _norm(frames), "--target", o["target"],
                "--cand-fps", o["cand_fps"], "--max-edge", str(min(int(o["max_edge"]), 1600)),
            ], state, "frames", 12,
                f"Hareket-farkinda kare secimi (hedef ~{o['target']} kare)...")
        else:
            cmd = [
                _norm(SPIRULA), "sam", "extract", _norm(norm), "-o", _norm(frames),
                "-s", o["skip"], "-k", o["keep"], "-q", "95",
            ]
            if int(o["max_frames"]) > 0:
                cmd += ["-n", o["max_frames"]]
            rc = _run(cmd, state, "frames", 12,
                      f"Videonun tamamindan kareler cikariliyor (skip={o['skip']})...")
        n_frames = len(list(frames.glob("*.jpg"))) + len(list(frames.glob("*.png")))
        if rc != 0 or n_frames < 8:
            raise RuntimeError(f"frame extraction failed ({n_frames} frames)")

        # 3) structure from motion ------------------------------------------
        sfm = work / "sfm"
        rc = _run([
            _norm(SPIRULA), "sfm", "auto", _norm(frames), "-o", _norm(sfm),
            "--data-type", "video", "--quality", "high", "--quiet",
        ], state, "sfm", 30, f"Kamera pozlari cikariliyor ({n_frames} kare)...")
        sparse = sfm / "sparse" / "0"
        if rc not in (0, 3) or not sparse.exists():
            raise RuntimeError(f"SfM failed (exit {rc})")

        # 4) dataset layout --------------------------------------------------
        dataset = work / "dataset"
        dataset.mkdir(parents=True, exist_ok=True)
        _junction(dataset / "images", frames)
        _junction(dataset / "sparse", sfm / "sparse")
        state.update(stage="dataset", progress=52, message="Veri seti hazirlaniyor...")

        # 5) train -----------------------------------------------------------
        runs = work / "runs"
        train_cmd = [
            _norm(SPIRULA), "train", "3dgs", "--data", _norm(dataset),
            "--output-dir-prefix", _norm(runs), "--output-dir-name", "run",
            "--num-iterations", o["iters"], "--quality", o["quality"],
            "--train-resolution-divisor", o["res_divisor"],
            "--floater-suppression", o["floater"],
            "--erank-reg", o["erank"],
            "--ppisp-exposure-from-exif", o["exif_exposure"],
            "--disable-viewer", "1", "--keep-viewer-alive", "0",
        ]
        if float(o["depth_reg"]) > 0:
            train_cmd += ["--depth-distortion-reg", o["depth_reg"]]
        if float(o["rgb_reg"]) > 0:
            train_cmd += ["--rgb-distortion-reg", o["rgb_reg"]]
        if o["distraction"] != "off":
            train_cmd += ["--distraction-robustness", o["distraction"]]
        if o["extra"]:
            train_cmd += o["extra"].split()
        rc = _run(train_cmd, state, "train", 55,
                  f"3D Gaussian egitiliyor ({o['iters']} adim, {o['quality']}, floater={o['floater']})... Birkac dakika surer.",
                  pct_end=92,
                  progress_re=re.compile(r"step[^\s]*\s*(\d+)\s*/", re.I),
                  progress_total=max(1, int(o["iters"])))
        splat = find_splat(runs)
        if rc != 0 or splat is None:
            raise RuntimeError(f"training failed (exit {rc})")

        shutil.copyfile(splat, result / "splat.ply")
        ckpt_dir = splat.parent
        outputs = {"splat": f"/files/{job_dir.name}/result/splat.ply"}
        state.update(stage="train", progress=94, message="Model kaydedildi.")

        # 6) optional mesh ---------------------------------------------------
        if o["mesh"]:
            rc = _run([
                _norm(SPIRULA), "mesh", _norm(ckpt_dir), "--data", _norm(dataset),
                "--output", _norm(result / "mesh"), "--format", "glb,ply", "--color", "texture",
            ], state, "mesh", 96, "Oda yuzeyi (mesh) cikariliyor...")
            for ext in ("glb", "ply", "obj"):
                f = result / f"mesh.{ext}"
                if f.exists():
                    outputs[ext] = f"/files/{job_dir.name}/result/mesh.{ext}"

        state.update(state="done", stage="done", progress=100, message="Tamamlandi.",
                     outputs=outputs, n_frames=n_frames)

        # open the finished model in Spirula Studio (the native viewer the user asked for)
        if o.get("open_studio") == "1":
            try:
                subprocess.Popen([_norm(SPIRULA), _norm(result / "splat.ply")],
                                 close_fds=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as exc:  # noqa: BLE001
                state["last_log"] = f"Studio acilamadi: {exc}"
    except Exception as exc:  # noqa: BLE001
        state.update(state="error", message=f"Hata: {exc}")
