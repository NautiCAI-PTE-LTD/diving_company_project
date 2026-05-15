"""Run all three vision models on one image and persist the result."""
from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import logging
import uuid

import numpy as np
from PIL import Image

from .. import config
from ..db import db_session, Image as ImageRow
from ..inference import _runtime as inf_runtime
from ..inference import region as region_model
from ..inference import before_after as ba_model
from ..inference import species as species_model
from ..inference import ocr as ocr_inference

log = logging.getLogger("nauticai.analyze")

# Thread pool used to run the three models in parallel. TF (before_after)
# runs on CPU, PyTorch (region, species) runs on the GPU when available,
# so they don't compete for the same compute — perfect speedup conditions.
# We share a single pool across requests to avoid spawn/teardown overhead.
_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="nauticai-inf")


# ---------------------------------------------------------------------------
# Ship-overview detector
# ---------------------------------------------------------------------------
# Goal: keep wide whole-ship photographs (the SILVERSTONE-style shot taken
# from a boat showing the entire vessel above water) OUT of the per-region
# photo grids and out of the AI fouling stats.  Diver close-ups taken
# underwater never see bright sky and almost never include text — that's
# the signal we exploit.
def _is_ship_overview(pil: Image.Image, region_conf: float) -> bool:
    """Return True if `pil` looks like a wide whole-ship shot rather than
    an underwater hull close-up.

    Signals combined (any TWO trigger):
      - Sky visible at top of the frame (bright, blue-shifted top strip)
      - Hull-region classifier is uncertain (confidence < 0.45)
      - Bright + low-saturation top strip (cloudy sky / overcast horizon)

    Tuned for the common case of phone / DSLR photos taken from a launch
    or pier showing the vessel above water.
    """
    try:
        arr = np.asarray(pil.convert("RGB"))
    except Exception:
        return False

    H, W, _ = arr.shape
    if H < 40 or W < 40:
        return False

    # Top 1/7th of the image — that's where the sky lives in any wide shot.
    top = arr[: max(1, H // 7), :, :].astype(np.float32)
    r, g, b = top[..., 0].mean(), top[..., 1].mean(), top[..., 2].mean()
    brightness = (r + g + b) / 3.0
    blue_dominance = b - r           # blue sky → b >> r
    sat_proxy = max(r, g, b) - min(r, g, b)

    sky_blue   = brightness > 130 and blue_dominance > 8
    sky_overcast = brightness > 175 and sat_proxy < 20   # bright but desaturated → cloud / sky
    low_confidence = region_conf < 0.45

    triggers = sum([sky_blue, sky_overcast, low_confidence])
    return triggers >= 2


def analyze_file(path: Path, *, original_filename: str,
                 image_id: str | None = None,
                 region_hint: str | None = None,
                 extra_meta: dict | None = None) -> dict:
    """
    1. Hull-region classifier (or use region_hint if user pre-tagged)
    2. Before/After classifier
    3. Species classifier
    Persist into the Image table and return a JSON-friendly dict.
    """
    image_id = image_id or uuid.uuid4().hex
    pil = Image.open(path).convert("RGB")
    W, H = pil.size

    # ----- Run the three vision models --------------------------------
    # On CUDA + TensorRT (Jetson), running region / before_after / species
    # in parallel deadlocks the GPU and hangs forever. Serialise there; keep
    # the thread-pool parallelism for CPU / PyTorch-only workstations.
    log.info("analyze %s · start (%dx%d)", image_id, W, H)
    _serial = config.DEVICE == "cuda" or inf_runtime.using_trt()

    if region_hint and region_hint in config.HULL_REGIONS:
        region = {"id": region_hint,
                  "display": config.HULL_REGION_DISPLAY.get(region_hint, region_hint),
                  "confidence": 1.0, "distribution": []}
    elif _serial:
        region = region_model.predict(pil)
    else:
        region = _POOL.submit(region_model.predict, pil).result()

    if _serial:
        stage = ba_model.predict(pil)
        species = species_model.predict(pil)
    else:
        stage_future = _POOL.submit(ba_model.predict, pil)
        species_future = _POOL.submit(species_model.predict, pil)
        stage = stage_future.result()
        species = species_future.result()

    # ----- Ship-overview filter --------------------------------------
    # If this looks like a wide whole-ship photo (sky visible, low region
    # confidence) we re-tag it as 'vessel_cover' so it is *kept* on the
    # report (as the OCR / cover photo) but excluded from the per-region
    # photo grids and the executive-summary stats. The fouling / before-
    # after models still run so the UI can show the verdict, but the row
    # never lands inside a hull-region bucket.
    is_overview = False
    if not region_hint:
        is_overview = _is_ship_overview(pil, float(region["confidence"]))
        if is_overview:
            log.info(
                "image %s detected as ship-overview "
                "(region was %s @ %.2f) — routing to vessel_cover",
                image_id, region["id"], region["confidence"])
            region = {
                "id": "vessel_cover",
                "display": "Vessel Overview (cover)",
                "confidence": 1.0,
                "distribution": [],
            }

    severity = config.severity_from(species["fouling_pct"], species["top"])
    log.info("analyze %s · done region=%s stage=%s species=%s",
             image_id, region["id"], stage["id"], species["top"])

    # ----- Auto-OCR for overview shots --------------------------------
    # When the image is the whole-ship overview that the wizard uses as
    # its PHOTOGRAPHIC REPORT cover, we also run vessel-name OCR right
    # here so the analyze response can pre-fill the Vessel & Job step.
    # Skipping OCR on close-up hull shots keeps the GPU free — there is
    # almost never any readable text underwater anyway.
    ocr_payload: dict | None = None
    if is_overview:
        try:
            ocr_payload = ocr_inference.extract(pil)
        except Exception:
            log.exception("auto-OCR on overview %s failed (non-fatal)", image_id)
            ocr_payload = None

    with db_session() as s:
        row = s.get(ImageRow, image_id)
        if row is None:
            row = ImageRow(id=image_id, filename=original_filename, path=str(path))
            s.add(row)
        row.filename = original_filename
        row.path = str(path)
        row.width, row.height = W, H
        row.region, row.region_conf = region["id"], float(region["confidence"])
        row.stage,  row.stage_conf  = stage["id"],  float(stage["confidence"])
        row.species_top   = species["top"]
        row.species_dist  = species["distribution"]
        row.fouling_pct   = float(species["fouling_pct"])
        row.severity      = severity
        if ocr_payload is not None:
            row.vessel_guess = ocr_payload.get("best_guess", "") or ""
            row.ocr_text = [
                {"text": c["text"], "confidence": c["confidence"]}
                for c in ocr_payload.get("candidates", [])
            ]

    out = {
        "image_id":   image_id,
        "filename":   original_filename,
        "width":  W,
        "height": H,
        "region": {"id": region["id"], "display": region["display"],
                   "confidence": region["confidence"]},
        "stage":   {"id": stage["id"], "confidence": stage["confidence"]},
        "species": {
            "top": species["top"],
            "top_display": species["top_display"],
            "distribution": [
                {"id": d["id"], "display": d["display"], "prob": d["prob"]}
                for d in species["distribution"]
            ],
        },
        "fouling_pct": species["fouling_pct"],
        "severity":    severity,
        # Hint for the UI: when True the image was filtered out of the
        # hull-region grids (it's a whole-ship overview shot — kept on the
        # report only as a cover photo).
        "is_overview": bool(is_overview),
    }
    if ocr_payload is not None:
        out["vessel_ocr"] = {
            "best_guess":      ocr_payload.get("best_guess", ""),
            "best_confidence": ocr_payload.get("best_confidence", 0.0),
            "candidates":      ocr_payload.get("candidates", []),
        }
    if extra_meta:
        out.update(extra_meta)
    return out
