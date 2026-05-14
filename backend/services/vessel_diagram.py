"""Per-region vessel side-view diagram generator.

For each section of the report we render a small line-drawing of the
vessel with a red ellipse circling the area being discussed — mirroring
the "Bow section." style image in the source `marine_service_report (2).pdf`.

The diagram is built once per region with Pillow (line drawing + red
highlight ellipse) and returned as a `reportlab.platypus.Image` flowable
ready to drop into the PDF story.

API
---
    diagram_for_region(region_id, display, width_mm=170) -> RLImage | None
"""
from __future__ import annotations
import io
from typing import Dict, Tuple, Optional

from PIL import Image as PILImage, ImageDraw, ImageFont

from reportlab.platypus import Image as RLImage
from reportlab.lib.units import mm


# ----- palette ---------------------------------------------------------
HULL_LINE = (10, 20, 41)      # ink-900
HULL_FILL = (255, 255, 255)
WATER     = (148, 163, 184)    # slate-400
RING      = (220, 38, 38)      # red-600
LABEL     = (10, 20, 41)

W, H = 1000, 240                # logical canvas (px)


def _ship_outline(d: ImageDraw.ImageDraw) -> None:
    """A simple tanker side-view in the (0..W, 0..H) canvas. Origin is
    top-left (PIL convention)."""
    # Convert "y-up" coords to PIL by subtracting from H. We'll define points
    # in y-up below for readability, then flip when calling polygon().
    def flip(pts):
        return [(x, H - y) for x, y in pts]

    # ----- main hull (waterline up + deck) -------------------------
    hull = [
        (60, 120),                # stern transom top
        (60, 100),                # transom down
        (75, 80), (95, 70), (130, 65),    # transom curve into bottom
        (820, 65),                # flat bottom run
        (880, 65), (920, 70), (940, 85),  # bow curve up
        (970, 110),               # rake up to bow stem
        (965, 130),               # bow stem (deck)
        (810, 130),
        # bridge superstructure
        (810, 165),
        (710, 165),
        (710, 175),               # bridge wing
        (680, 175),
        (680, 165),
        (630, 165),
        (630, 130),
        # cargo deck (3 small crane bumps)
        (560, 130), (560, 150), (545, 150), (545, 130),
        (420, 130), (420, 150), (405, 150), (405, 130),
        (280, 130), (280, 150), (265, 150), (265, 130),
        (150, 130),
        # stern superstructure stub
        (150, 155),
        (95, 155),
        (95, 120),
    ]
    d.polygon(flip(hull), fill=HULL_FILL, outline=HULL_LINE)

    # bulbous bow
    bulb = [(940, 95), (965, 80), (985, 88), (980, 100), (940, 90)]
    d.polygon(flip(bulb), fill=HULL_FILL, outline=HULL_LINE)

    # rudder
    rud = [(48, 100), (62, 100), (62, 65), (48, 65)]
    d.polygon(flip(rud), fill=HULL_FILL, outline=HULL_LINE)
    # propeller hub
    cx, cy, rx, ry = 75, 75, 8, 12
    d.ellipse([cx - rx, H - cy - ry, cx + rx, H - cy + ry],
              fill=HULL_FILL, outline=HULL_LINE)
    # propeller cross
    d.line([(cx - rx, H - cy), (cx + rx, H - cy)], fill=HULL_LINE, width=1)
    d.line([(cx, H - cy - ry), (cx, H - cy + ry)], fill=HULL_LINE, width=1)

    # waterline (dashed)
    _dashed_line(d, (20, H - 95), (990, H - 95), WATER, dash=10, gap=6, width=1)


def _dashed_line(d: ImageDraw.ImageDraw, p0, p1, color, dash=8, gap=4, width=1):
    x0, y0 = p0
    x1, y1 = p1
    if y0 != y1:
        return  # only horizontal supported (sufficient for waterline)
    x = x0
    while x < x1:
        d.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width)
        x += dash + gap


# ---------- region → highlight ellipse (cx, cy, rx, ry) in y-up coords
REGION_OVERLAY: Dict[str, Tuple[int, int, int, int]] = {
    "Bow":                 (945,  95, 55, 35),
    "Verticle_Slide":      (480, 100, 280, 30),     # whole hull side
    "Flat_bottom":         (480,  65, 300, 18),
    "Bilege_keels":        (480,  78, 240, 14),
    "Sea_chest":           (620,  72,  35, 14),
    "stren":               (110,  85,  65, 30),
    "Rope":                ( 82,  78,  22, 14),
    "Propeller":           ( 75,  75,  20, 20),
    "Radder":              ( 55,  82,  18, 26),
    "Cathodic_Protection": (820,  78,  60, 14),
    "EGCS":                (660, 160,  35, 16),
}


def _font(size: int) -> ImageFont.ImageFont:
    """Best-effort TTF; falls back to PIL's default bitmap font."""
    for name in ("arialbi.ttf", "arial.ttf", "DejaVuSans-Bold.ttf",
                 "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def diagram_for_region(region_id: str, display: Optional[str] = None,
                        width_mm: float = 170) -> Optional[RLImage]:
    """Returns a `reportlab.platypus.Image` of the side-view vessel with
    a red circle highlighting `region_id`.  Falls back to None on any
    rendering error so the PDF generator can skip the diagram gracefully.
    """
    try:
        img = PILImage.new("RGB", (W, H), (255, 255, 255))
        d = ImageDraw.Draw(img)
        _ship_outline(d)

        # overlay red ellipse for this region
        ov = REGION_OVERLAY.get(region_id)
        if ov:
            cx, cy, rx, ry = ov
            # multi-stroke for a slightly thicker outline (PIL outline=1px)
            for w in (3, 2, 1):
                d.ellipse([cx - rx - w, H - cy - ry - w,
                            cx + rx + w, H - cy + ry + w],
                           outline=RING)

        # caption — "Bow section."
        if display:
            label = display.strip().rstrip(".") + "."
            d.text((20, 10), label, fill=LABEL, font=_font(22))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        # preserve aspect
        target_w = width_mm * mm
        target_h = target_w * (H / W)
        return RLImage(buf, width=target_w, height=target_h)
    except Exception:
        return None
