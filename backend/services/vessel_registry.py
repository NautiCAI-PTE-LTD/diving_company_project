"""Company vessel registry + OCR resolution (known vs new vessels).

Workflow
--------
1. **Known fleet** — client maintains ``/api/vessels`` (names + aliases).
2. **Per image** — EasyOCR returns candidates; this module resolves them.
3. **Per report** — wizard may pin ``vessel_name``; uploads constrained to that
   name when set, or suggest best match / flag **new_vessel** for review.

Resolution outcomes (``match_kind``)
------------------------------------
- ``exact`` / ``fuzzy`` — matched registry entry
- ``discovery`` — strong OCR name not in registry (propose add to fleet)
- ``no_nameplate`` — no usable hull text
- ``pinned`` — report already has vessel_name; OCR must agree or warn

Use from analyze, ``/api/images/{id}/vessel-ocr``, and PDF cover pickers.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from typing import TYPE_CHECKING

from .vessel_discovery import (
    normalize_vessel_name,
    names_match,
    ocr_guess_score,
    vessel_ocr_from_candidate_list,
    _resolve_ocr_picks,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Painted on hull but not the ship name (same as OCR module)
_REGISTRY_MARKS = frozenset({
    "MONROVIA", "LIBERIA", "PANAMA", "MALTA", "HAMILTON", "NASSAU", "BAHAMAS",
    "SINGAPORE", "HONGKONG", "CYPRUS", "MARSHALL", "MAJURO", "ISLE", "MAN",
})


@dataclass
class VesselEntry:
    """One vessel in the company directory."""
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class VesselResolveResult:
    """Result of matching OCR to known fleet or discovering a new name."""
    display_name: str
    match_kind: str  # exact | fuzzy | discovery | no_nameplate | pinned | conflict
    confidence: float
    score: float
    raw_ocr: str
    registry_id: Optional[str] = None
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    needs_review: bool = False
    review_reason: str = ""


def _fuzzy_ratio(a: str, b: str) -> float:
    na, nb = normalize_vessel_name(a), normalize_vessel_name(b)
    if not na or not nb:
        return 0.0
    if na == nb or na in nb or nb in na:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def match_to_registry(
    text: str,
    fleet: list[VesselEntry],
    *,
    min_fuzzy: float = 0.78,
) -> tuple[Optional[VesselEntry], str, float]:
    """Return (entry, kind, ratio) for best registry hit or None."""
    t = (text or "").strip()
    if not t or normalize_vessel_name(t) in _REGISTRY_MARKS:
        return None, "", 0.0

    best_entry: Optional[VesselEntry] = None
    best_kind = ""
    best_r = 0.0

    for entry in fleet:
        names = [entry.name, *entry.aliases]
        for nm in names:
            if names_match(t, nm):
                r = 1.0
                kind = "exact"
            else:
                r = _fuzzy_ratio(t, nm)
                kind = "fuzzy" if r >= min_fuzzy else ""
            if r > best_r:
                best_r, best_entry, best_kind = r, entry, kind

    if best_entry and best_kind:
        return best_entry, best_kind, best_r
    return None, "", 0.0


def _candidates_from_payload(ocr_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = ocr_payload.get("candidates") or []
    if not raw and ocr_payload.get("best_guess"):
        raw = [{
            "text": ocr_payload.get("best_guess", ""),
            "confidence": float(ocr_payload.get("best_confidence") or 0),
        }]
    return [
        {"text": (c.get("text") or "").strip(), "confidence": float(c.get("confidence") or 0)}
        for c in raw
        if (c.get("text") or "").strip()
    ]


def _pick_best_raw_line(candidates: list[dict[str, Any]]) -> tuple[str, float, float]:
    """Heuristic best line before registry (smart pick equivalent)."""
    if not candidates:
        return "", 0.0, 0.0
    picks = []
    for c in candidates:
        g = c["text"]
        conf = c["confidence"]
        picks.append({
            "best_guess": g,
            "confidence": conf,
            "score": ocr_guess_score(g, conf),
        })
    best = _resolve_ocr_picks(picks)
    if not best:
        return "", 0.0, 0.0
    return best["best_guess"], float(best["confidence"]), float(best["score"])


def resolve_vessel_ocr(
    ocr_payload: dict[str, Any],
    fleet: list[VesselEntry],
    *,
    pinned_name: str = "",
    min_fuzzy: float = 0.78,
    min_discovery_conf: float = 0.55,
) -> VesselResolveResult:
    """
    Resolve OCR to a vessel name.

    * **pinned_name** set (report wizard): prefer registry match to that name;
      if OCR strongly disagrees → ``conflict`` + ``needs_review``.
    * **fleet** non-empty: scan all lines for registry; best score wins.
    * **no registry match** but good OCR → ``discovery`` (new vessel).
    """
    candidates = _candidates_from_payload(ocr_payload)
    raw, conf, score = _pick_best_raw_line(candidates)

    alts: list[dict[str, Any]] = []
    for c in candidates[:8]:
        entry, kind, ratio = match_to_registry(c["text"], fleet, min_fuzzy=min_fuzzy)
        alts.append({
            "text": c["text"],
            "confidence": c["confidence"],
            "registry_match": entry.name if entry else None,
            "match_kind": kind or None,
            "ratio": round(ratio, 3),
        })

    if not raw:
        return VesselResolveResult(
            display_name=pinned_name or "",
            match_kind="no_nameplate",
            confidence=0.0,
            score=0.0,
            raw_ocr="",
            alternatives=alts,
        )

    # --- Pinned vessel on report ---
    if pinned_name.strip():
        pin_entry, pin_kind, pin_r = match_to_registry(pinned_name, fleet, min_fuzzy=0.99)
        ocr_entry, ocr_kind, ocr_r = match_to_registry(raw, fleet, min_fuzzy=min_fuzzy)
        if names_match(raw, pinned_name):
            return VesselResolveResult(
                display_name=pinned_name.strip(),
                match_kind="pinned",
                confidence=conf,
                score=score,
                raw_ocr=raw,
                registry_id=pin_entry.id if pin_entry else None,
                alternatives=alts,
            )
        if ocr_entry and ocr_kind and ocr_r >= min_fuzzy and not names_match(ocr_entry.name, pinned_name):
            return VesselResolveResult(
                display_name=pinned_name.strip(),
                match_kind="conflict",
                confidence=conf,
                score=score,
                raw_ocr=raw,
                registry_id=pin_entry.id if pin_entry else None,
                alternatives=alts,
                needs_review=True,
                review_reason=f"OCR read '{raw}' but report vessel is '{pinned_name}'",
            )
        return VesselResolveResult(
            display_name=pinned_name.strip(),
            match_kind="pinned",
            confidence=conf,
            score=score,
            raw_ocr=raw,
            alternatives=alts,
            needs_review=conf < min_discovery_conf,
            review_reason="Low OCR confidence for pinned vessel" if conf < min_discovery_conf else "",
        )

    # --- Match against company fleet (any candidate line) ---
    best_entry: Optional[VesselEntry] = None
    best_kind = ""
    best_r = 0.0
    best_conf = 0.0
    best_raw = raw

    for c in candidates:
        entry, kind, ratio = match_to_registry(c["text"], fleet, min_fuzzy=min_fuzzy)
        if not entry:
            continue
        q = ocr_guess_score(c["text"], c["confidence"]) * ratio
        if q > best_r or (q == best_r and len(c["text"]) > len(best_raw)):
            best_entry, best_kind, best_r = entry, kind, q
            best_conf = c["confidence"]
            best_raw = c["text"]

    if best_entry:
        return VesselResolveResult(
            display_name=best_entry.name,
            match_kind=best_kind,
            confidence=best_conf,
            score=best_r,
            raw_ocr=best_raw,
            registry_id=best_entry.id,
            alternatives=alts,
        )

    # --- New vessel discovery ---
    if conf >= min_discovery_conf and len(normalize_vessel_name(raw)) >= 4:
        return VesselResolveResult(
            display_name=raw,
            match_kind="discovery",
            confidence=conf,
            score=score,
            raw_ocr=raw,
            alternatives=alts,
            needs_review=True,
            review_reason="Name not in company vessel list — confirm or add vessel",
        )

    return VesselResolveResult(
        display_name=raw,
        match_kind="discovery",
        confidence=conf,
        score=score,
        raw_ocr=raw,
        alternatives=alts,
        needs_review=True,
        review_reason="Weak OCR — confirm vessel name",
    )


def suggest_report_vessel_from_images(
    image_rows: list[Any],
    fleet: list[VesselEntry],
    *,
    pinned_name: str = "",
) -> VesselResolveResult:
    """Automated batch vessel + cover from raw uploads (registry optional)."""
    from . import vessel_auto as vessel_auto_mod

    batch = vessel_auto_mod.auto_discover_from_images(
        image_rows, fleet, pinned_name=pinned_name,
    )
    return VesselResolveResult(
        display_name=batch.display_name,
        match_kind=batch.match_kind,
        confidence=batch.confidence,
        score=batch.score,
        raw_ocr=batch.raw_ocr,
        registry_id=batch.registry_id,
        alternatives=batch.candidates,
        needs_review=batch.needs_review,
        review_reason=batch.review_reason,
    )


def load_fleet_entries(session: "Session", company_id: str) -> list[VesselEntry]:
    """Load company vessel directory for OCR resolution."""
    from ..db import Vessel as VesselRow

    rows = (
        session.query(VesselRow)
        .filter(VesselRow.company_id == company_id)
        .order_by(VesselRow.name.asc())
        .all()
    )
    out: list[VesselEntry] = []
    for row in rows:
        aliases = row.aliases if isinstance(row.aliases, list) else []
        out.append(VesselEntry(
            id=row.id,
            name=(row.name or "").strip(),
            aliases=[str(a).strip() for a in aliases if str(a).strip()],
        ))
    return out


def resolution_to_dict(resolved: VesselResolveResult) -> dict[str, Any]:
    return {
        "display_name": resolved.display_name,
        "match_kind": resolved.match_kind,
        "confidence": resolved.confidence,
        "score": resolved.score,
        "raw_ocr": resolved.raw_ocr,
        "registry_id": resolved.registry_id,
        "needs_review": resolved.needs_review,
        "review_reason": resolved.review_reason or "",
        "alternatives": resolved.alternatives,
    }


def apply_resolution_to_ocr_payload(
    ocr_payload: dict[str, Any],
    resolved: VesselResolveResult,
) -> dict[str, Any]:
    """Merge resolver output into API OCR payload (mutates copy)."""
    out = dict(ocr_payload)
    vo = dict(out.get("vessel_ocr") or out)
    if resolved.display_name:
        vo["best_guess"] = resolved.display_name
        vo["best_confidence"] = resolved.confidence
    vo["vessel_resolution"] = resolution_to_dict(resolved)
    out["vessel_ocr"] = vo
    out["best_guess"] = vo.get("best_guess", out.get("best_guess", ""))
    out["best_confidence"] = vo.get("best_confidence", out.get("best_confidence", 0.0))
    out["vessel_resolution"] = vo["vessel_resolution"]
    return out


def resolve_ocr_payload_for_company(
    ocr_payload: dict[str, Any],
    fleet: list[VesselEntry],
    *,
    pinned_name: str = "",
) -> tuple[VesselResolveResult, dict[str, Any]]:
    """Run resolver and return (result, merged API payload)."""
    from . import vessel_auto as vessel_auto_mod

    resolved = vessel_auto_mod.auto_resolve_single(
        ocr_payload, fleet, pinned_name=pinned_name,
    )
    merged = apply_resolution_to_ocr_payload(ocr_payload, resolved)
    return resolved, merged
