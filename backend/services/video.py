"""ROV / dive video → image frames.

Strategy
--------
1. Open the video with OpenCV.
2. Sample one frame every ``stride_sec`` seconds (default 2.0). For a 30-s clip
   at 30 FPS that gives ~15 frames — enough to characterise each region the
   diver swam past without overwhelming the AI pipeline.
3. Drop frames that are obviously useless:
     * almost solid blue/black (no hull visible)
     * very blurry (low Laplacian variance — water turbulence / camera motion)
4. Cap the total number of frames at ``max_frames`` (default 24) so we never
   blow up on huge files.
5. Persist each surviving frame to ``storage/uploads/<uuid>.jpg`` and return
   the list of (image_id, path, ts_sec) tuples.

The endpoint then feeds these paths into the standard ``analyze_file`` so the
same 3 vision models run on each.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import logging
import uuid

import cv2
import numpy as np

from .. import config

log = logging.getLogger("nauticai.video")

# OpenCV needs an actual container extension — keep this list explicit so the
# Frontend can mirror it as its `accept` filter.
SUPPORTED_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


@dataclass
class Frame:
    image_id: str
    path: Path
    ts_sec: float
    blurriness: float  # lower = blurrier


def is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_VIDEO_EXTS


def _save_video_temp(content: bytes, original_filename: str) -> Path:
    suffix = Path(original_filename).suffix.lower() or ".mp4"
    if suffix not in SUPPORTED_VIDEO_EXTS:
        suffix = ".mp4"
    dest = config.UPLOADS_DIR / f"_video_{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(content)
    return dest


def _laplacian_variance(gray: np.ndarray) -> float:
    """Higher value = sharper frame. <60 ≈ noticeably blurry."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _is_mostly_solid(bgr: np.ndarray, thresh: float = 9.0) -> bool:
    """True for near-uniform frames (e.g. solid water, lens cap, surface)."""
    return float(bgr.std()) < thresh


def extract_frames(content: bytes, original_filename: str,
                   stride_sec: float = 2.0,
                   max_frames: int = 24,
                   min_sharpness: float = 60.0) -> tuple[list[Frame], dict]:
    """Return (frames, meta). Meta carries fps/duration/dropped counts."""
    src = _save_video_temp(content, original_filename)
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        src.unlink(missing_ok=True)
        raise RuntimeError("Could not open video — codec may be unsupported.")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total / fps if fps else 0.0
    step = max(int(round(fps * stride_sec)), 1)

    frames: list[Frame] = []
    dropped_blurry = 0
    dropped_blank = 0
    idx = 0
    try:
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            if idx % step == 0:
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                sharp = _laplacian_variance(gray)
                if _is_mostly_solid(bgr):
                    dropped_blank += 1
                elif sharp < min_sharpness:
                    dropped_blurry += 1
                else:
                    image_id = uuid.uuid4().hex
                    out = config.UPLOADS_DIR / f"{image_id}.jpg"
                    # JPEG quality 92 is a good size/clarity trade-off for these AIs.
                    cv2.imwrite(str(out), bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
                    frames.append(Frame(
                        image_id=image_id, path=out,
                        ts_sec=round(idx / fps, 2),
                        blurriness=sharp,
                    ))
                    if len(frames) >= max_frames:
                        break
            idx += 1
    finally:
        cap.release()
        src.unlink(missing_ok=True)

    log.info(
        "video: %s  fps=%.1f dur=%.1fs kept=%d blurry=%d blank=%d",
        original_filename, fps, duration, len(frames), dropped_blurry, dropped_blank,
    )

    return frames, {
        "duration_sec": round(duration, 2),
        "fps": round(fps, 2),
        "total_frames_scanned": idx,
        "frames_kept": len(frames),
        "frames_dropped_blurry": dropped_blurry,
        "frames_dropped_blank": dropped_blank,
        "stride_sec": stride_sec,
    }
