"""Vessel cover helpers — model outputs + OCR-linked photographic cover.

Hull vs cover grids: models only (``not_hull`` / ``vessel_cover``).

Photographic Report opener photo: the image where OCR read the vessel name
(step-1 detection), when ``NAUTICAI_PHOTO_COVER_MATCH_OCR_NAME=1`` (default).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, Protocol

from .. import config
from . import storage as storage_svc


class _ImageLike(Protocol):
    id: str
    path: str
    region: str
    stage: str
    species_top: str
    vessel_guess: str
    ocr_text: Any
    stage_conf: float


def is_model_cover(*, stage: dict[str, Any], species: dict[str, Any]) -> bool:
    """True when classifiers say this is a whole-ship / not-hull photo (not a hull grid shot)."""
    stage_id = (stage or {}).get("id") or ""
    species_top = (species or {}).get("top") or ""
    return stage_id == "not_hull" or species_top == config.SPECIES_VESSEL_COVER_ID


def is_cover_image_row(row: _ImageLike) -> bool:
    """DB/analyze row classified as whole-ship / not-hull (never a hull grid shot)."""
    if (row.region or "") == "vessel_cover":
        return True
    if (row.stage or "") == "not_hull":
        return True
    if (row.species_top or "") == config.SPECIES_VESSEL_COVER_ID:
        return True
    return False


def normalize_vessel_name(name: str) -> str:
    """Loose match for OCR vs report vessel name."""
    s = (name or "").upper().strip()
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s


def names_match(a: str, b: str) -> bool:
    na, nb = normalize_vessel_name(a), normalize_vessel_name(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


_WEAK_GUESSES = frozenset({
    "TUG", "TUGS", "MV", "MS", "MT", "NA", "NB", "IT", "OR", "VS",
    "FPSO", "OSV", "AHTS", "LNG", "LPG", "RTV",
})
_REGISTRY_MARKS = frozenset({
    "MONROVIA", "LIBERIA", "PANAMA", "MALTA", "HAMILTON", "NASSAU", "BAHAMAS",
    "SINGAPORE", "HONGKONG", "CYPRUS", "MARSHALL", "MAJURO",
})


def ocr_guess_score(guess: str, confidence: float) -> float:
    """Rank OCR names — penalise short hull noise (e.g. TUG) vs real nameplates."""
    g = normalize_vessel_name(guess)
    conf = float(confidence or 0)
    if not g or conf <= 0:
        return 0.0
    score = conf
    n = len(g)
    if g in _WEAK_GUESSES or g in _REGISTRY_MARKS:
        score *= 0.12
    elif n <= 3:
        score *= 0.2
    elif n == 4 and conf < 0.92:
        score *= 0.45
    elif n < 6 and conf < 0.75:
        score *= 0.55
    elif n >= 6:
        score *= 1.05
    return min(score, 1.0)


def ocr_confidence_from_row(row: _ImageLike) -> float:
    """Best OCR candidate confidence stored on the image row."""
    texts = row.ocr_text or []
    if isinstance(texts, list) and texts:
        return max(float(t.get("confidence", 0) or 0) for t in texts)
    return 0.0


def ocr_quality_from_row(row: _ImageLike) -> float:
    """Quality score for picking cover / name (not raw confidence alone)."""
    conf = ocr_confidence_from_row(row)
    guess = (row.vessel_guess or "").strip()
    if guess:
        return ocr_guess_score(guess, conf)
    return conf


def pick_photographic_cover_image(
    images: list[_ImageLike],
    *,
    preferred_id: str | None = None,
    vessel_name: str | None = None,
    min_ocr_conf: float = 0.20,
) -> Optional[_ImageLike]:
    """
    Image for the PDF Photographic Report opener (vessel name + one photo).

    Priority:
      1. ``preferred_id`` from the wizard (step-1 OCR image id) when file exists
      2. Any analysed image whose OCR ``vessel_guess`` matches ``vessel_name``
      3. Model-cover shots with strongest OCR
    """
    living = [
        img for img in images
        if storage_svc.resolve_image_path(getattr(img, "id", ""), getattr(img, "path", ""))
    ]
    if not living:
        return None

    vn = (vessel_name or "").strip()

    # Wizard / report ``vessel_image_id`` always wins when the file exists.
    if preferred_id:
        pref = next((i for i in living if i.id == preferred_id), None)
        if pref is not None:
            return pref

    if vn and config.PHOTO_COVER_MATCH_OCR_NAME:
        matched = [
            i for i in living
            if (i.vessel_guess or "").strip()
            and names_match(i.vessel_guess, vn)
            and ocr_confidence_from_row(i) >= min_ocr_conf
        ]
        if matched:
            return max(matched, key=ocr_quality_from_row)
        matched_loose = [
            i for i in living
            if (i.vessel_guess or "").strip() and names_match(i.vessel_guess, vn)
        ]
        if matched_loose:
            return max(matched_loose, key=ocr_quality_from_row)

    pool = [img for img in living if is_cover_image_row(img)]
    if not pool:
        pool = [img for img in living if (img.stage or "") == "not_hull"]
    if not pool:
        return None

    if preferred_id:
        pref = next((i for i in pool if i.id == preferred_id), None)
        if pref is not None:
            return pref

    with_name = [
        i for i in pool
        if (i.vessel_guess or "").strip()
        and ocr_confidence_from_row(i) >= min_ocr_conf
    ]
    if with_name:
        return max(with_name, key=ocr_quality_from_row)

    named = [i for i in pool if (i.vessel_guess or "").strip()]
    if named:
        return max(named, key=ocr_quality_from_row)

    not_hull = [i for i in pool if (i.stage or "") == "not_hull"]
    if not_hull:
        return max(not_hull, key=lambda i: float(i.stage_conf or 0))

    return pool[0]


def vessel_ocr_from_candidate_list(
    candidates: list[dict[str, Any]],
    *,
    image_id: str,
) -> dict[str, Any]:
    """Build API payload from OCR lines (stored or fresh extract)."""
    picks: list[dict[str, Any]] = []
    for c in candidates:
        text = (c.get("text") or c.get("best_guess") or "").strip()
        if not text:
            continue
        conf = float(c.get("confidence") or c.get("best_confidence") or 0.0)
        picks.append({
            "best_guess": text,
            "confidence": conf,
            "score": ocr_guess_score(text, conf),
            "image_id": image_id,
        })
    best = _resolve_ocr_picks(picks)
    out_cands = [
        {
            "text": (c.get("text") or c.get("best_guess") or "").strip(),
            "confidence": float(c.get("confidence") or c.get("best_confidence") or 0.0),
            **({"box": c["box"]} if c.get("box") else {}),
        }
        for c in candidates
        if (c.get("text") or c.get("best_guess") or "").strip()
    ][:8]
    guess = (best or {}).get("best_guess") or ""
    conf = float((best or {}).get("confidence") or 0.0)
    return {
        "image_id": image_id,
        "url": f"/api/images/{image_id}/file",
        "candidates": out_cands,
        "best_guess": guess,
        "best_confidence": conf,
        "vessel_ocr": {
            "best_guess": guess,
            "best_confidence": conf,
            "image_id": image_id,
            "candidates": out_cands,
        },
    }


def _resolve_ocr_picks(picks: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Prefer full nameplate (SILVERSTONE) over shorter mis-read (VERSTONE)."""
    if not picks:
        return None
    pool = [p for p in picks if p.get("best_guess")
            and normalize_vessel_name(p["best_guess"]) not in _REGISTRY_MARKS]
    pool = pool or picks
    pool.sort(key=lambda p: -float(p.get("score") or 0))
    top = float(pool[0].get("score") or 0)
    tier = [p for p in pool if float(p.get("score") or 0) >= top * 0.82]
    tier.sort(key=lambda p: (-len(p.get("best_guess") or ""), -float(p.get("score") or 0)))
    best = tier[0]
    for pick in pool:
        pg = normalize_vessel_name(pick.get("best_guess") or "")
        bg = normalize_vessel_name(best.get("best_guess") or "")
        shared = (
            len(pg) > len(bg) >= 4
            and (bg in pg or (len(pg) >= 5 and len(bg) >= 5 and pg[-5:] == bg[-5:]))
            and float(pick.get("score") or 0) >= float(best.get("score") or 0) * 0.65
        )
        if shared:
            best = pick
    return best


def pick_best_vessel_ocr(
    candidates: list[dict[str, Any]],
    *,
    cover_only: bool = False,
) -> Optional[dict[str, Any]]:
    """Choose {best_guess, confidence, image_id} from analyze/OCR rows."""
    picks: list[dict[str, Any]] = []
    for c in candidates:
        if cover_only and not (
            c.get("cover_only")
            or (c.get("stage") or {}).get("id") == "not_hull"
            or (c.get("species") or {}).get("top") == config.SPECIES_VESSEL_COVER_ID
        ):
            continue
        vo = c.get("vessel_ocr") or c
        image_id = vo.get("image_id") or c.get("image_id") or ""
        ocr_cands = vo.get("candidates") or c.get("candidates")
        if isinstance(ocr_cands, list) and ocr_cands:
            for oc in ocr_cands:
                guess = (oc.get("text") or oc.get("best_guess") or "").strip()
                if not guess:
                    continue
                conf = float(oc.get("confidence") or oc.get("best_confidence") or 0.0)
                picks.append({
                    "best_guess": guess,
                    "confidence": conf,
                    "score": ocr_guess_score(guess, conf),
                    "image_id": image_id,
                })
            continue
        guess = (c.get("best_guess") or vo.get("best_guess") or "").strip()
        if not guess:
            continue
        conf = float(vo.get("best_confidence") or vo.get("confidence") or 0.0)
        picks.append({
            "best_guess": guess,
            "confidence": conf,
            "score": ocr_guess_score(guess, conf),
            "image_id": image_id,
        })
    return _resolve_ocr_picks(picks)
