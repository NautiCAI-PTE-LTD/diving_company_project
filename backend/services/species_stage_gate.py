"""Stage-aware correction for species predictions (temporary until retrain).

The species CNN often calls fouled *before* photos ``clean_paint``. After-cleaning
photos should lean toward clean when the model sees any real clean signal.

Rules (``config.SPECIES_STAGE_GATE``):

  **before** — no priority for ``clean_paint``:
    • If top is ``clean_paint`` → switch to best fouling class (algae, barnacles, …).
    • Fouling %% floor so severity is not marked Clean (D).

  **after** — priority for ``clean_paint`` when plausible:
    • If ``clean_paint`` prob ≥ boost threshold → prefer ``clean_paint`` as top
      (low fouling %%), unless another class is overwhelmingly dominant.
    • Heavy fouling still visible after cleaning (e.g. barnacles @ 75%+) → keep fouling.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import config
from .. import species_registry as species_reg

log = logging.getLogger("nauticai.species_gate")


def _fouling_ids() -> list[str]:
    return [s for s in config.SPECIES if species_reg.is_fouling_class(s)]


def _fouling_pct_from_distribution(distribution: list[dict]) -> float:
    pct = sum(float(d.get("prob", 0) or 0) for d in distribution if d.get("id") != "clean_paint")
    return round(pct * 100.0, 1)


def _entry(distribution: list[dict], class_id: str) -> dict | None:
    for d in distribution:
        if d.get("id") == class_id:
            return d
    return None


def _pick_top_fouling(distribution: list[dict]) -> dict | None:
    for d in distribution:
        if d.get("id") in _fouling_ids():
            return d
    return None


def _apply_clean_top(species: dict[str, Any], dist: list[dict], *, reason: str,
                     raw_top: str, raw_prob: float) -> dict[str, Any]:
    clean = _entry(dist, "clean_paint") or {"id": "clean_paint", "prob": raw_prob}
    out = dict(species)
    out["top"] = "clean_paint"
    out["top_display"] = config.SPECIES_DISPLAY.get("clean_paint", "Clean Paint")
    out["fouling_pct"] = _fouling_pct_from_distribution(dist)
    out["stage_gated"] = True
    out["stage_gate_reason"] = reason
    out["raw_top"] = raw_top
    out["raw_top_prob"] = round(raw_prob, 4)
    log.info(
        "species stage gate: prefer clean_paint (was %s@%.3f) fouling=%.1f%% (%s)",
        raw_top, raw_prob, out["fouling_pct"], reason,
    )
    return out


def _apply_fouling_top(species: dict[str, Any], dist: list[dict], *, reason: str,
                       raw_top: str, raw_prob: float, stage_id: str) -> dict[str, Any]:
    fouling_top = _pick_top_fouling(dist)
    if fouling_top is None:
        fouling_top = {
            "id": "algae",
            "display": config.SPECIES_DISPLAY.get("algae", "Algae"),
            "prob": 0.0,
        }
    new_top_id = fouling_top["id"]
    new_fouling_pct = _fouling_pct_from_distribution(dist)
    if new_fouling_pct < 10.0 and stage_id == "before":
        new_fouling_pct = max(new_fouling_pct, 15.0)

    out = dict(species)
    out["top"] = new_top_id
    out["top_display"] = config.SPECIES_DISPLAY.get(new_top_id, new_top_id)
    out["fouling_pct"] = new_fouling_pct
    out["stage_gated"] = True
    out["stage_gate_reason"] = reason
    out["raw_top"] = raw_top
    out["raw_top_prob"] = round(raw_prob, 4)
    log.info(
        "species stage gate: stage=%s reject clean (%s@%.3f) -> %s fouling=%.1f%% (%s)",
        stage_id, raw_top, raw_prob, new_top_id, new_fouling_pct, reason,
    )
    return out


def apply(species: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
    if (stage or {}).get("id") in ("not_hull",):
        return species
    """Return a possibly adjusted species result dict (same shape as ``species.predict``)."""
    if not config.SPECIES_STAGE_GATE:
        return species

    stage_id = (stage.get("id") or "").strip().lower()
    if stage_id not in config.STAGES:
        return species

    dist = list(species.get("distribution") or [])
    if not dist:
        return species

    top_entry = dist[0]
    top_id = top_entry.get("id") or ""
    top_prob = float(top_entry.get("prob", 0) or 0)
    clean_entry = _entry(dist, "clean_paint")
    clean_prob = float((clean_entry or {}).get("prob", 0) or 0)

    # ----- BEFORE: never prioritize clean_paint --------------------------------
    if stage_id == "before":
        if top_id == "clean_paint":
            return _apply_fouling_top(
                species, dist,
                reason="before_no_clean_priority",
                raw_top=top_id, raw_prob=top_prob, stage_id=stage_id,
            )
        return species

    # ----- AFTER: prioritize clean_paint when the signal is there --------------
    if stage_id == "after":
        if top_id == "clean_paint":
            return species
        if clean_prob < config.SPECIES_CLEAN_AFTER_MIN_PROB:
            return species
        if top_id in _fouling_ids() and top_prob >= config.SPECIES_AFTER_KEEP_FOULING_MIN:
            return species
        return _apply_clean_top(
            species, dist,
            reason="after_prefer_clean",
            raw_top=top_id, raw_prob=top_prob,
        )

    return species
