"""Species class list synced from the trained bundle (11-class or legacy 5-class)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import config

# Report / PDF display names (all supported ids).
SPECIES_DISPLAY_MAP: dict[str, str] = {
    "vessel_cover": "Vessel cover",
    "clean_paint": "Clean Paint",
    "slime": "Slime",
    "algae": "Algae",
    "grass": "Grass",
    "macroalgae": "Grass / Algae",  # legacy bundle id
    "barnacles": "Barnacles",
    "mussels": "Mussels",
    "tubeworms": "Tube worms",
    "goosenecks": "Goosenecks",
    "calcareous": "Calcareous deposits",
    "mixed_fouling": "Mixed fouling",
}

FOULING_CLASS_IDS = frozenset({
    "slime", "algae", "grass", "macroalgae", "barnacles", "mussels",
    "tubeworms", "goosenecks", "calcareous", "mixed_fouling",
})

_NON_FOULING_IDS = frozenset({"clean_paint", "vessel_cover"})

_loaded: list[str] | None = None


def load_class_names() -> list[str]:
    global _loaded
    if _loaded is not None:
        return _loaded
    try:
        import torch
        ckpt = torch.load(str(config.SPECIES_CKPT), map_location="cpu", weights_only=False)
        names = list(ckpt.get("meta", {}).get("class_names") or [])
        if names:
            _loaded = names
            return names
    except Exception:
        pass
    _loaded = list(config.SPECIES_FALLBACK)
    return _loaded


def sync_config() -> list[str]:
    """Push bundle class list into config.SPECIES / SPECIES_DISPLAY."""
    names = load_class_names()
    config.SPECIES = names
    config.SPECIES_DISPLAY = {k: SPECIES_DISPLAY_MAP.get(k, k.replace("_", " ").title()) for k in names}
    return names


def display_name(class_id: str) -> str:
    return SPECIES_DISPLAY_MAP.get(class_id, class_id.replace("_", " ").title())


def is_fouling_class(class_id: str) -> bool:
    if class_id in _NON_FOULING_IDS:
        return False
    if class_id in FOULING_CLASS_IDS:
        return True
    return class_id not in _NON_FOULING_IDS and class_id in load_class_names()
