"""Resize helpers — large camera JPEGs are downscaled before CNN inference."""
from __future__ import annotations

from PIL import Image

from .. import config


def resize_max_edge(pil: Image.Image, max_edge: int) -> Image.Image:
    """Keep aspect ratio; no-op if already small enough."""
    pil = pil.convert("RGB")
    w, h = pil.size
    longest = max(w, h)
    if longest <= max_edge:
        return pil
    scale = max_edge / float(longest)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return pil.resize((nw, nh), Image.BILINEAR)


def for_inference(pil: Image.Image) -> Image.Image:
    return resize_max_edge(pil, config.INFERENCE_MAX_EDGE)


def for_ocr(pil: Image.Image) -> Image.Image:
    return resize_max_edge(pil, config.OCR_MAX_EDGE)
