"""Vessel-name OCR via EasyOCR (PyTorch CRAFT detector + CRNN recogniser).

Vessel names are usually:
  • painted in capital letters on the bow / stern
  • the largest text on the hull
  • alphabetical (sometimes with a space, e.g. "GLEN COVE")

Heuristic ranking
-----------------
score = confidence · log(1 + bbox_area_normalised) · alphabet_purity
Then we pick the highest-scoring line as the vessel-name guess. We expose every
candidate so the UI can show a confidence-ranked list.
"""
from __future__ import annotations
from threading import Lock
from typing import Optional, List, Dict, Any
import logging
import math
import re

import numpy as np
from PIL import Image

from .. import config

log = logging.getLogger("nauticai.ocr")

_LOCK = Lock()
_READER = None


def _load() -> None:
    global _READER
    if _READER is not None:
        return
    import easyocr
    log.info("Initialising EasyOCR (langs=%s, gpu=%s)", config.OCR_LANGS, config.OCR_GPU)
    _READER = easyocr.Reader(config.OCR_LANGS, gpu=config.OCR_GPU, verbose=False)


_ALPHA = re.compile(r"[A-Za-z]")
_NOISE = re.compile(r"^[\W_0-9]+$")


def _alphabet_purity(s: str) -> float:
    if not s:
        return 0.0
    letters = sum(1 for ch in s if ch.isalpha())
    return letters / len(s)


def _looks_like_vessel_name(s: str) -> bool:
    s = s.strip()
    if len(s) < 3 or len(s) > 30:
        return False
    if _NOISE.match(s):
        return False
    if not _ALPHA.search(s):
        return False
    # Reject pure dates / times, e.g. "08/31/2024" or "07:29"
    if re.fullmatch(r"[\d/:\-\s]+", s):
        return False
    return _alphabet_purity(s) >= 0.6


def _normalise(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s.upper()


def _upscale(rgb: np.ndarray, target_short: int = 1280) -> np.ndarray:
    """Bilinearly enlarge tiny photos so the CRAFT detector can find the text.

    Smartphone photos shot from far away often have the vessel name covering
    only ~100px — upscaling to ~1280 short-edge consistently lifts EasyOCR
    confidence by 0.1-0.3 in our tests.
    """
    import cv2  # local import — already a project dep
    H, W = rgb.shape[:2]
    short = min(H, W)
    if short >= target_short:
        return rgb
    scale = target_short / float(short)
    new = (int(W * scale), int(H * scale))
    return cv2.resize(rgb, new, interpolation=cv2.INTER_CUBIC)


def _clamp_long_edge(rgb: np.ndarray, max_long: int) -> np.ndarray:
    """Downscale if the long edge is larger than `max_long`.

    Smartphone / DSLR photos can be 4000-6000 px on the long edge which
    pushes EasyOCR's intermediate tensors over 1 GB and trips the CPU
    allocator (``DefaultCPUAllocator: not enough memory``).  Clamping the
    long edge avoids the crash and only costs a tiny bit of OCR accuracy.
    """
    import cv2
    H, W = rgb.shape[:2]
    longest = max(H, W)
    if longest <= max_long:
        return rgb
    scale = max_long / float(longest)
    new = (max(1, int(W * scale)), max(1, int(H * scale)))
    return cv2.resize(rgb, new, interpolation=cv2.INTER_AREA)


def _safe_readtext(rgb: np.ndarray):
    """Call EasyOCR with progressively smaller images on out-of-memory.

    EasyOCR's PyTorch tensors can OOM on large images. We try a sensible
    starting size (2400 px long edge), and if that still fails we step
    down to 1800 → 1280 → 900. Returns ``[]`` if all attempts fail.
    """
    for max_long in (2400, 1800, 1280, 900):
        try:
            shrunk = _clamp_long_edge(rgb, max_long=max_long)
            return _READER.readtext(shrunk, detail=1, paragraph=False)
        except (RuntimeError, MemoryError) as e:
            # PyTorch allocator failure / Python OOM — back off and retry
            log.warning("OCR failed at max_long=%d (%s); retrying smaller",
                        max_long, str(e).split("\n", 1)[0][:120])
            try:
                import torch
                if hasattr(torch.cuda, "empty_cache"):
                    torch.cuda.empty_cache()
            except Exception:
                pass
            continue
    log.error("OCR aborted — image too large even at 900 px long edge")
    return []


def _merge_two_line_names(raw_results) -> List[tuple]:
    """Some vessels show their name across two stacked lines (e.g.
    "GLEN" / "COVE"). When two confident detections sit roughly above one
    another with similar widths, merge them into a single candidate.

    Returns the original list + any merged synthetic entries.
    """
    out = list(raw_results)
    n = len(raw_results)
    for i in range(n):
        bi, ti, ci = raw_results[i]
        for j in range(i + 1, n):
            bj, tj, cj = raw_results[j]
            if not (ti and tj):
                continue
            xi = [p[0] for p in bi]; yi = [p[1] for p in bi]
            xj = [p[0] for p in bj]; yj = [p[1] for p in bj]
            wi, hi = max(xi) - min(xi), max(yi) - min(yi)
            wj, hj = max(xj) - min(xj), max(yj) - min(yj)
            # Stacked vertically? (similar x-extent, j is just below i)
            x_overlap = min(max(xi), max(xj)) - max(min(xi), min(xj))
            if x_overlap < 0.5 * min(wi, wj):
                continue
            vgap = min(yj) - max(yi)
            if not (0 <= vgap <= 1.5 * max(hi, hj)):
                continue
            if abs(wi - wj) > 0.6 * max(wi, wj):
                continue
            merged_box = [
                [min(min(xi), min(xj)), min(min(yi), min(yj))],
                [max(max(xi), max(xj)), min(min(yi), min(yj))],
                [max(max(xi), max(xj)), max(max(yi), max(yj))],
                [min(min(xi), min(xj)), max(max(yi), max(yj))],
            ]
            out.append((merged_box, f"{ti} {tj}", (ci + cj) / 2.0))
    return out


def extract(pil_img: Image.Image) -> Dict[str, Any]:
    """Run OCR and return ranked candidates + best guess for the vessel name.

    Pipeline:
      1. Up-sample if the image is smaller than 1280 on the short edge.
      2. Run EasyOCR (CRAFT + CRNN).
      3. Try to merge two-line stacked names ("SS GLEN" / "COVE").
      4. Heuristic score = conf × log(1 + bbox area) × alphabet purity.
    """
    with _LOCK:
        _load()

    rgb = np.array(pil_img.convert("RGB"))
    # First clamp very large photos so the OCR allocator doesn't blow up,
    # then upscale tiny ones so CRAFT can still find small painted text.
    rgb = _clamp_long_edge(rgb, max_long=2400)
    rgb = _upscale(rgb, target_short=1280)
    H, W = rgb.shape[:2]
    img_area = float(H * W) or 1.0

    raw = _safe_readtext(rgb)
    enriched = _merge_two_line_names(raw)

    candidates: List[Dict[str, Any]] = []
    for box, text, conf in enriched:
        text_n = _normalise(str(text))
        if not _looks_like_vessel_name(text_n):
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        area_norm = area / img_area
        score = float(conf) * (1.0 + math.log1p(area_norm * 100.0)) * _alphabet_purity(text_n)
        candidates.append({
            "text": text_n,
            "confidence": float(conf),
            "box": [[float(x), float(y)] for (x, y) in box],
            "area_norm": area_norm,
            "score": score,
        })

    candidates.sort(key=lambda r: -r["score"])
    best = candidates[0] if candidates else None
    return {
        "candidates": [
            {"text": c["text"], "confidence": c["confidence"], "box": c["box"]}
            for c in candidates[:8]
        ],
        "best_guess": best["text"] if best else "",
        "best_confidence": best["confidence"] if best else 0.0,
    }
