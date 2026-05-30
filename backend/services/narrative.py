"""Generate the natural-language sentences that fill the
'Fouling Conditions Executive Summary' table.

Each row uses a **surveyor-style sentence template** (fixed grammar), but
**species**, **coverage %**, **thickness range**, **severity**, and
**cleaning Yes/No** all come from the AI analysis of *your* uploaded images
(``cluster.cluster_images`` → ``species_counts`` + ``avg_fouling``). Nothing
is copied from a reference PDF.

Methodology
-----------
1. **Per-location templates** (see ``LOCATION_TEMPLATES``) hold the fixed
   phrasing for each of the 12 standard locations the surveyor inspects.
2. **Species** detected by the AI classifier are mapped to the casing
   surveyors use in the template ("Slime", "barnacles", "Algae", …).
   When two species are co-dominant, the sentence reads
   *"fouled by Slime and barnacles"*.
3. **Thickness** is **always** a millimetre **range** (e.g. *"2-4mm"*).
   For each analysed photo we map that image's fouling **%** and **top
   species** to a conservative mm band, then **average** those bands for
   the survey location (journal-style scale — not a single region-mean %
   pushed through one high bracket).
4. **Severity (A/B/C/D)** and **Cleaning (Yes/No)** are derived from the
   coverage % using the same scale shown at the bottom of the source
   template:  A=Light · B=Moderate · C=Heavy · D=Clean.
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple


# --------------------------------------------------------------- templates
# 12 location IDs match the rows of the source PDF's executive-summary
# table. Each sentence is written exactly the way it appears in the
# template; only {species} and {thickness} are injected.
LOCATION_TEMPLATES: Dict[str, str] = {
    "Bow": (
        "The condition of plating of the bulbous bow area as visual "
        "inspection is fouled by {species} with {thickness} of thickness."
    ),
    "PortSide": (
        "The condition of side shell / vertical side at portside area as "
        "visual inspection from forward to aft ward is fouled by {species} "
        "with {thickness} of thickness."
    ),
    "Starboard": (
        "The condition of side shell / vertical side at STB side area as "
        "visual inspection from forward to aft ward is fouled by {species} "
        "with {thickness} of thickness."
    ),
    "Flat_bottom": (
        "The condition of flat bottom hull as visual inspection from "
        "bottom forward to aft ward is fouled by {species} with "
        "{thickness} of thickness."
    ),
    "DryDocking": (
        "The condition of dry docking marks flat bottom hull as visual "
        "inspection from bottom forward to aft ward is fouled by "
        "{species} with {thickness} of thickness."
    ),
    "Bilege_keels": (
        "The condition of bilge keel at portside and starboard side area "
        "as visual inspection from fore tip to aft tip and flat bar is "
        "fouled by {species} with {thickness} of thickness."
    ),
    "stren": (
        "The condition of stern area as visual inspection is fouled by "
        "{species} with {thickness} of thickness."
    ),
    "Sea_chest": (
        "The condition of the sea chest gratings is fouled by {species} "
        "with {thickness} of thickness."
    ),
    "Radder": (
        "The condition of shell plating of rudder blade as visual "
        "inspection from top to bottom is fouled by {species} with "
        "{thickness} of thickness."
    ),
    "RudderPintle": (
        "The condition of rudder pintle frame as visual inspection from "
        "top to bottom is fouled by {species} with {thickness} of "
        "thickness."
    ),
    "Rope": (
        "The condition of rope guard as visual inspection is fouled by "
        "{species} with {thickness} of thickness."
    ),
    "Propeller": (
        "The propeller blades, as visual inspection on all blades are "
        "fouled by {species} with {thickness} of thickness."
    ),
}


# Per-location phrasing for the *clean* case (coverage < 10 %). Uses the
# same opening structure as the fouled sentence so the table reads
# consistently.
CLEAN_TEMPLATES: Dict[str, str] = {
    "Bow":          "The plating of the bulbous bow area as visual inspection appears clean with no significant fouling observed.",
    "PortSide":     "The side shell / vertical side at portside area as visual inspection from forward to aft ward appears clean.",
    "Starboard":    "The side shell / vertical side at STB side area as visual inspection from forward to aft ward appears clean.",
    "Flat_bottom":  "The flat bottom hull as visual inspection from bottom forward to aft ward appears clean.",
    "DryDocking":   "The dry docking marks on flat bottom hull as visual inspection appear clean.",
    "Bilege_keels": "The bilge keel at portside and starboard side as visual inspection appears clean.",
    "stren":        "The stern area as visual inspection appears clean with no significant fouling observed.",
    "Sea_chest":    "The sea chest gratings as visual inspection appear clean with no significant fouling observed.",
    "Radder":       "The shell plating of rudder blade as visual inspection from top to bottom appears clean.",
    "RudderPintle": "The rudder pintle frame as visual inspection from top to bottom appears clean.",
    "Rope":         "The rope guard as visual inspection appears clean with no significant fouling observed.",
    "Propeller":    "The propeller blades, as visual inspection on all blades appear clean with no significant fouling observed.",
}


# ----------------------------------------------------------- species naming
# Species classes from the AI model → label used in the report sentence.
# Casing follows the source PDF exactly:
#   - "Slime" stays capitalised (surveyor's standard term for biofilm /
#     short algae growth — which is what our 'algae' class mostly catches)
#   - "barnacles", "mussels", "Algae" (macroalgae) follow template casing
SPECIES_LABEL = {
    "slime": "Slime",
    "algae": "Algae",
    "macroalgae": "Algae",
    "grass": "grass",
    "barnacles": "Barnacles",
    "mussels": "Mussels",
    "tubeworms": "tube worms",
    "goosenecks": "goosenecks",
    "calcareous": "calcareous deposits",
    "mixed_fouling": "mixed fouling",
    "clean_paint": "clean paint",
    "vessel_cover": "clean paint",
}

SPECIES_LABEL_SECONDARY = {
    "slime": "slime",
    "algae": "algae",
    "macroalgae": "algae",
    "grass": "grass",
    "barnacles": "barnacles",
    "mussels": "mussels",
    "tubeworms": "tube worms",
    "goosenecks": "goosenecks",
    "calcareous": "calcareous deposits",
    "mixed_fouling": "mixed fouling",
    "clean_paint": "clean paint",
    "vessel_cover": "clean paint",
}

_HARD_SPECIES = {"barnacles", "mussels", "goosenecks", "tubeworms", "calcareous"}


# --------------------------------------------------------- thickness model
# Per-image bands from AI fouling % (species classifier). Conservative vs
# the old region-only table so clients do not see inflated "5-7mm" rows.
_IMAGE_BRACKETS_SOFT: List[Tuple[float, Tuple[int, int]]] = [
    (10,  (0, 1)),
    (25,  (1, 2)),
    (45,  (1, 3)),
    (65,  (2, 4)),
    (80,  (2, 5)),
    (101, (3, 6)),
]
_IMAGE_BRACKETS_HARD: List[Tuple[float, Tuple[int, int]]] = [
    (10,  (0, 1)),
    (25,  (1, 3)),
    (45,  (2, 4)),
    (65,  (3, 5)),
    (80,  (4, 6)),
    (101, (5, 8)),
]


def _image_thickness_mm(pct: float, top_species: str) -> Tuple[int, int]:
    """One photo → (lo, hi) mm from its AI fouling % and dominant species."""
    sid = (top_species or "").strip()
    if sid in ("clean_paint", "vessel_cover") or pct < 10:
        return (0, 1)
    brackets = _IMAGE_BRACKETS_HARD if sid in _HARD_SPECIES else _IMAGE_BRACKETS_SOFT
    for limit, band in brackets:
        if pct < limit:
            return band
    return brackets[-1][1]


def _format_mm_range(lo: float, hi: float) -> str:
    lo_i = max(0, int(round(lo)))
    hi_i = max(lo_i + 1, int(round(hi)))
    if hi_i - lo_i < 1:
        hi_i = lo_i + 1
    return f"{lo_i}-{hi_i}mm"


def thickness_range_from_analysed_images(images: List[dict]) -> str:
    """Average per-image thickness bands for all photos in a hull region."""
    if not images:
        return "0-1mm"
    los: list[float] = []
    his: list[float] = []
    for im in images:
        pct = float(im.get("fouling_pct") or 0.0)
        top = (im.get("species_top") or "unknown").strip()
        lo, hi = _image_thickness_mm(pct, top)
        los.append(float(lo))
        his.append(float(hi))
    return _format_mm_range(sum(los) / len(los), sum(his) / len(his))


def thickness_range(pct: float, top_species: str) -> str:
    """Fallback: single mean % + dominant species (legacy callers)."""
    lo, hi = _image_thickness_mm(pct, top_species)
    return _format_mm_range(lo, hi)


def severity_letter(pct: float, top: str) -> str:
    """A / B / C / D — same scale shown at the bottom of the template."""
    if top == "clean_paint" or pct < 10:
        return "D"          # Clean
    if pct < 35:
        return "A"          # Light
    if pct < 65:
        return "B"          # Moderate
    return "C"              # Heavy


def cleaning_recommended(pct: float, top: str) -> bool:
    """Cleaning gets ticked 'Yes' when there is meaningful fouling."""
    return top != "clean_paint" and pct >= 30


def _species_phrase(primary: str, secondary: Optional[str]) -> str:
    """Build the 'Slime' / 'Slime and barnacles' fragment."""
    primary_lbl = SPECIES_LABEL.get(primary, primary.capitalize())
    if not secondary:
        return primary_lbl
    sec_lbl = SPECIES_LABEL_SECONDARY.get(secondary, secondary.lower())
    return f"{primary_lbl} and {sec_lbl}"


# ------------------------------------------------- main entry points
def narrative_for_location(template_id: str,
                            meta: Dict[str, Any]) -> Dict[str, Any]:
    """Generate the executive-summary row for a single location.

    Args:
        template_id: one of the keys in ``LOCATION_TEMPLATES`` (Bow,
            PortSide, Starboard, …).
        meta: per-region cluster meta from ``services.cluster`` —
            must expose ``species_counts`` (dict[str, int]) and
            ``avg_fouling`` (float % coverage).

    Returns dict with:
        sentence, primary_species, secondary_species,
        thickness, pct, severity, cleaning, image_count
    """
    species_counts: Dict[str, int] = dict(meta.get("species_counts", {}))
    pct: float                       = float(meta.get("avg_fouling", 0.0) or 0.0)
    image_count                      = int(meta.get("count", 0) or 0)

    fouling = {
        k: v for k, v in species_counts.items()
        if k not in ("clean_paint", "vessel_cover") and v > 0
    }

    # ---- "clean" branch ----------------------------------------
    if not fouling or pct < 10:
        return {
            "sentence":          CLEAN_TEMPLATES.get(
                template_id,
                "This location appears clean with no significant fouling observed.",
            ),
            "primary_species":   "clean_paint",
            "secondary_species": None,
            "thickness":         "0-1mm",
            "pct":               round(pct, 0),
            "severity":          "D",
            "cleaning":          False,
            "image_count":       image_count,
        }

    # ---- "fouled" branch ---------------------------------------
    sorted_sp = sorted(fouling.items(), key=lambda kv: -kv[1])
    primary, primary_n = sorted_sp[0]
    secondary: Optional[str] = None
    if len(sorted_sp) > 1:
        sec, sec_n = sorted_sp[1]
        # a secondary species is only mentioned if it's a meaningful
        # fraction of the dominant — otherwise the surveyor would skip it
        if sec_n >= 0.25 * primary_n:
            secondary = sec

    thickness = (meta.get("thickness_range") or "").strip()
    if not thickness:
        thickness = thickness_range(pct, primary)
    species_phrase = _species_phrase(primary, secondary)

    tpl = LOCATION_TEMPLATES.get(
        template_id,
        # safe fall-back — same shape as the most generic row in the
        # template ("Stern area")
        "The condition of {location} as visual inspection is fouled by "
        "{species} with {thickness} of thickness.",
    )
    sentence = tpl.format(
        species=species_phrase,
        thickness=thickness,
        location=template_id.replace("_", " ").lower(),
    )

    return {
        "sentence":          sentence,
        "primary_species":   primary,
        "secondary_species": secondary,
        "thickness":         thickness,
        "pct":               round(pct, 0),
        "severity":          severity_letter(pct, primary),
        "cleaning":          cleaning_recommended(pct, primary),
        "image_count":       image_count,
    }


# ------------- legacy alias (kept for callers passing region_id) ----------
# The 11 hull-region IDs from the AI model map 1:1 to the templates above
# (most use the same key). The two synthetic locations — Starboard and
# RudderPintle — must be requested via narrative_for_location() directly.
def narrative_for_region(region_id: str,
                          meta: Dict[str, Any]) -> Dict[str, Any]:
    return narrative_for_location(region_id, meta)
