"""Run all three vision models on one image and persist the result."""
from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import logging
import uuid

from PIL import Image

from .. import config
from ..db import db_session, Image as ImageRow
from ..inference import _runtime as inf_runtime
from ..inference import region as region_model
from ..inference import before_after as ba_model
from ..inference import species as species_model
from ..inference import ocr as ocr_inference
from .species_stage_gate import apply as apply_species_stage_gate
from . import vessel_discovery as vessel_disc
from . import vessel_registry as vessel_reg
from .image_prep import for_inference, for_ocr

log = logging.getLogger("nauticai.analyze")


def _serial_inference() -> bool:
    """Return True when the three classifiers must run one-after-another."""
    if inf_runtime.using_trt():
        return True
    if config.DEVICE != "cuda":
        return False
    r = inf_runtime.resolve(config.SHIP_REGION_CKPT)
    s = inf_runtime.resolve(config.SPECIES_CKPT)
    b = inf_runtime.resolve(config.BEFORE_AFTER_CKPT)
    # Parallel OK when exported ONNX/TRT backs the GPU (no dual PyTorch on CUDA).
    if r.backend != "native" and s.backend != "native":
        return False
    return r.backend == "native" and s.backend == "native" and b.backend == "native"


# Thread pool used to run the three models in parallel. TF (before_after)
# runs on CPU, PyTorch (region, species) runs on the GPU when available,
# so they don't compete for the same compute — perfect speedup conditions.
# We share a single pool across requests to avoid spawn/teardown overhead.
_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="nauticai-inf")


def _cover_region() -> dict:
    return {
        "id": "vessel_cover",
        "display": "Vessel Overview (cover)",
        "confidence": 1.0,
        "distribution": [],
    }


def analyze_file(path: Path, *, original_filename: str,
                 image_id: str | None = None,
                 region_hint: str | None = None,
                 extra_meta: dict | None = None,
                 company_id: str | None = None,
                 pinned_vessel_name: str = "") -> dict:
    """
    1. Hull-region classifier (or use region_hint if user pre-tagged)
    2. Before/After classifier (before | after | not_hull)
    3. Species classifier (incl. vessel_cover)

    Cover vs hull grids: **models only** (not_hull or species vessel_cover).
    OCR runs on model-selected cover shots for the Photographic Report.
    """
    image_id = image_id or uuid.uuid4().hex
    pil_raw = Image.open(path).convert("RGB")
    W, H = pil_raw.size
    pil = for_inference(pil_raw)

    log.info("analyze %s · start (%dx%d)", image_id, W, H)
    _serial = _serial_inference()

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

    species = apply_species_stage_gate(species, stage)

    species_top_raw = species.get("top") or ""
    cover_only = vessel_disc.is_model_cover(stage=stage, species=species)
    ba_not_hull = (stage.get("id") or "") == "not_hull"
    species_model_cover = species_top_raw == config.SPECIES_VESSEL_COVER_ID

    if cover_only:
        log.info(
            "image %s · model cover (stage=%s species=%s)",
            image_id, stage.get("id"), species_top_raw,
        )
        region = _cover_region()
        if species_model_cover:
            species = {
                **species,
                "top": "clean_paint",
                "top_display": "N/A (cover photo)",
                "fouling_pct": 0.0,
                "cover_skipped": True,
            }

    severity = config.severity_from(species.get("fouling_pct", 0), species.get("top", ""))

    ocr_payload: dict | None = None
    if cover_only:
        try:
            ocr_payload = ocr_inference.extract(for_ocr(pil_raw))
        except Exception:
            log.exception("vessel OCR on cover %s failed (non-fatal)", image_id)

    ocr_guess = (ocr_payload or {}).get("best_guess") or ""
    ocr_conf = float((ocr_payload or {}).get("best_confidence") or 0.0)
    vessel_resolution: dict | None = None

    if ocr_payload is not None:
        fleet: list[vessel_reg.VesselEntry] = []
        if company_id:
            with db_session() as s:
                fleet = vessel_reg.load_fleet_entries(s, company_id)
        _resolved, ocr_payload = vessel_reg.resolve_ocr_payload_for_company(
            ocr_payload,
            fleet,
            pinned_name=(pinned_vessel_name or "").strip(),
        )
        vessel_resolution = vessel_reg.resolution_to_dict(_resolved)
        ocr_guess = _resolved.display_name or ocr_guess
        ocr_conf = _resolved.confidence or ocr_conf

    log.info(
        "analyze %s · done region=%s stage=%s species=%s cover_only=%s",
        image_id, region["id"], stage["id"], species.get("top"), cover_only,
    )

    with db_session() as s:
        row = s.get(ImageRow, image_id)
        if row is None:
            row = ImageRow(id=image_id, filename=original_filename, path=str(path))
            s.add(row)
        row.filename = original_filename
        row.path = str(path)
        row.width, row.height = W, H
        row.region, row.region_conf = region["id"], float(region["confidence"])
        row.stage, row.stage_conf = stage["id"], float(stage["confidence"])
        row.species_top = species.get("top", "clean_paint")
        row.species_dist = species.get("distribution", [])
        row.fouling_pct = float(species.get("fouling_pct", 0))
        row.severity = severity
        if ocr_payload is not None:
            row.vessel_guess = ocr_guess
            row.ocr_text = [
                {"text": c["text"], "confidence": c["confidence"]}
                for c in ocr_payload.get("candidates", [])
            ]

    out = {
        "image_id": image_id,
        "filename": original_filename,
        "width": W,
        "height": H,
        "region": {
            "id": region["id"],
            "display": region["display"],
            "confidence": region["confidence"],
        },
        "stage": {"id": stage["id"], "confidence": float(stage["confidence"])},
        "species": {
            "top": species["top"],
            "top_display": species.get("top_display", species["top"]),
            "distribution": [
                {"id": d["id"], "display": d["display"], "prob": d["prob"]}
                for d in species.get("distribution", [])
            ],
        },
        "fouling_pct": species.get("fouling_pct", 0),
        "severity": severity,
        "species_stage_gated": bool(species.get("stage_gated")),
        "is_overview": cover_only,
        "cover_only": cover_only,
        "fouling_analysis_skipped": cover_only,
        "routing": "model",
    }
    if ba_not_hull:
        out["ba_not_hull"] = True
    if species_model_cover:
        out["species_model_cover"] = True
    if ocr_payload is not None:
        out["vessel_ocr"] = {
            "best_guess": ocr_guess,
            "best_confidence": ocr_conf,
            "image_id": image_id,
            "candidates": ocr_payload.get("candidates", []),
            "vessel_resolution": vessel_resolution,
        }
        if vessel_resolution:
            out["vessel_resolution"] = vessel_resolution
    if species.get("stage_gated"):
        out["species_raw_top"] = species.get("raw_top")
        out["species_stage_gate_reason"] = species.get("stage_gate_reason")
    if extra_meta:
        out.update(extra_meta)
    return out
