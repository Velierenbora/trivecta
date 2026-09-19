"""Adaptive (motion-aware) video frame extraction, a faithful port of Spirula's
FrameMotion + plan_by_motion (docs/datasets.md "Frames out of a video").

coverage  = share of the frame's content that left it, from the fitted affine
parallax  = 75th percentile of the flow the affine could not explain
cost      = coverage + 2 * parallax
Frames are then spaced at equal cumulative cost to hit a target count, and the
sharpest frame in a small window around each pick is kept.
"""
import argparse
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

FEATURES = 500
ANALYSIS_W = 320


def decode_candidates(ffmpeg: str, video: str, out_dir: Path, fps: float, max_edge: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.jpg"):
        f.unlink()
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error", "-i", video,
        "-vf", f"fps={fps},scale='min({max_edge},iw)':-2",
        "-q:v", "3", str(out_dir / "%05d.jpg"),
    ], check=False)
    return sorted(out_dir.glob("*.jpg"))


def motion_cost(prev_gray, gray) -> float:
    pts = cv2.goodFeaturesToTrack(prev_gray, FEATURES, 0.01, 8)
    if pts is None or len(pts) < 20:
        return 0.25
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None)
    if nxt is None:
        return 0.25
    ok = st.ravel() == 1
    if ok.sum() < 20:
        return 0.25
    a, b = pts[ok].reshape(-1, 2), nxt[ok].reshape(-1, 2)
    m, inl = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    h, w = prev_gray.shape[:2]
    if m is None:
        return 0.3
    # coverage: frame rect carried by the model, cut back to the frame
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32).reshape(-1, 1, 2)
    warped = cv2.transform(corners, m).reshape(-1, 2).astype(np.float32)
    inter, _ = cv2.intersectConvexConvex(warped, corners.reshape(-1, 2).astype(np.float32))
    coverage = float(np.clip(1.0 - inter / (w * h), 0.0, 1.0))
    # parallax: residual of inlier flow after the affine, 75th percentile
    pred = a @ m[:, :2].T + m[:, 2]
    res = np.linalg.norm(pred - b, axis=1) / np.hypot(w, h)
    parallax = float(np.percentile(res, 75))
    return coverage + 2.0 * parallax


def sharpness(gray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def plan(costs: list[float], target: int) -> list[int]:
    n = len(costs)
    if target >= n:
        return list(range(n))
    cum = np.concatenate([[0.0], np.cumsum(costs)])
    total = cum[-1]
    picks: list[int] = []
    if total <= 0:
        return list(np.linspace(0, n - 1, target).astype(int))
    step = total / target
    k = 0
    for i in range(n):
        if cum[i] >= k * step:
            picks.append(i)
            k += 1
    if picks and picks[0] != 0:
        picks.insert(0, 0)
    if picks and picks[-1] != n - 1:
        picks.append(n - 1)
    return picks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", type=int, default=350)
    ap.add_argument("--cand-fps", type=float, default=10.0)
    ap.add_argument("--max-edge", type=int, default=1600)
    ap.add_argument("--window", type=int, default=2)
    a = ap.parse_args()

    out = Path(a.out)
    cand = out.parent / "candidates"
    c = decode_candidates(a.ffmpeg, a.video, cand, a.cand_fps, a.max_edge)
    if len(c) < 8:
        raise SystemExit(f"too few candidate frames ({len(c)})")

    grays, downs = [], []
    for p in c:
        img = cv2.imread(str(p))
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        grays.append(g)
        downs.append(cv2.resize(g, (ANALYSIS_W, int(ANALYSIS_W * g.shape[0] / g.shape[1]))))

    costs = [motion_cost(downs[i], downs[i + 1]) for i in range(len(downs) - 1)]
    picks = plan(costs, a.target)

    # keep the sharpest frame in a small window around each pick
    final = []
    for i in picks:
        lo, hi = max(0, i - a.window), min(len(c) - 1, i + a.window)
        best = max(range(lo, hi + 1), key=lambda j: sharpness(grays[j]))
        final.append(best)
    final = sorted(set(final))

    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.jpg"):
        f.unlink()
    for k, idx in enumerate(final):
        shutil.copyfile(c[idx], out / f"{k:05d}.jpg")
    print(f"candidates={len(c)} kept={len(final)} target={a.target}")


if __name__ == "__main__":
    main()
