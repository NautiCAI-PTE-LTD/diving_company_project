"""Fully automated vessel naming from raw uploads (no client vessel list required).

Pipeline
--------
1. Models mark cover / nameplate photos (``not_hull`` / ``vessel_cover``).
2. EasyOCR on those images → ranked text lines.
3. Smart pick (longest name, drop MONROVIA, VERSTONE→SILVERSTONE rules).
4. Batch: cluster similar OCR names across images → one vessel + cover photo.

Optional company ``/api/vessels`` list only *boosts* matches when present.
"""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from ..inference import ocr as ocr_inference
from . import vessel_discovery as vd
from . import vessel_registry as vessel_reg
from . import storage as storage_svc
from .image_prep import for_ocr

log = logging.getLogger("nauticai.vessel_auto")

_AUTO_MIN_CONF = 0.50
_CLUSTER_SIM = 0.82


def _title_name(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if s.isupper() and len(s) > 3:
        return s.title()
    return s


def _cluster_key(name: str) -> str:
    return vd.normalize_vessel_name(name)


def _names_same_cluster(a: str, b: str) -> bool:
    ka, kb = _cluster_key(a), _cluster_key(b)
    if not ka or not kb:
        return False
    if ka == kb or ka in kb or kb in ka:
        return True
    if len(ka) >= 5 and len(kb) >= 5 and ka[-5:] == kb[-5:]:
        return True
    return difflib.SequenceMatcher(None, ka, kb).ratio() >= _CLUSTER_SIM


def _share_suffix(a: str, b: str, n: int = 5) -> bool:
    ka, kb = _cluster_key(a), _cluster_key(b)
    if not ka or not kb:
        return False
    k = min(n, len(ka), len(kb))
    return ka[-k:] == kb[-k:]


@dataclass
class _NameHit:
    display: str
    raw: str
    confidence: float
    score: float
    image_id: str
    is_cover: bool = False
    match_kind: str = "auto"


@dataclass
class AutoVesselBatchResult:
    display_name: str = ""
    match_kind: str = "no_nameplate"
    confidence: float = 0.0
    score: float = 0.0
    raw_ocr: str = ""
    cover_image_id: Optional[str] = None
    registry_id: Optional[str] = None
    needs_review: bool = False
    review_reason: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    image_count: int = 0
    nameplate_count: int = 0


def auto_resolve_single(
    ocr_payload: dict[str, Any],
    fleet: Optional[list[vessel_reg.VesselEntry]] = None,
    *,
    pinned_name: str = "",
) -> vessel_reg.VesselResolveResult:
    """Resolve one image OCR — automated first; registry only when fleet provided."""
    fleet = fleet or []
    if fleet:
        return vessel_reg.resolve_vessel_ocr(ocr_payload, fleet, pinned_name=pinned_name)

    pinned = (pinned_name or "").strip()
    if pinned:
        return vessel_reg.resolve_vessel_ocr(ocr_payload, [], pinned_name=pinned)

    candidates = vessel_reg._candidates_from_payload(ocr_payload)
    raw, conf, score = vessel_reg._pick_best_raw_line(candidates)
    alts = [{"text": c["text"], "confidence": c["confidence"]} for c in candidates[:8]]

    if not raw or len(_cluster_key(raw)) < 4:
        return vessel_reg.VesselResolveResult(
            display_name="",
            match_kind="no_nameplate",
            confidence=0.0,
            score=0.0,
            raw_ocr=raw or "",
            alternatives=alts,
        )

    display = _title_name(raw)
    weak = conf < _AUTO_MIN_CONF
    return vessel_reg.VesselResolveResult(
        display_name=display,
        match_kind="auto",
        confidence=conf,
        score=score,
        raw_ocr=raw,
        alternatives=alts,
        needs_review=weak,
        review_reason="Low OCR confidence — confirm vessel name" if weak else "",
    )


def _run_ocr_on_row(row: Any) -> dict[str, Any]:
    image_id = getattr(row, "id", "") or ""
    resolved = storage_svc.resolve_image_path(image_id, getattr(row, "path", ""))
    if not resolved or not Path(resolved).exists():
        return {}
    try:
        pil = Image.open(resolved).convert("RGB")
        return ocr_inference.extract(for_ocr(pil))
    except Exception:
        log.exception("auto OCR failed for %s", image_id)
        return {}


def _hit_from_row(row: Any, fleet: list[vessel_reg.VesselEntry]) -> Optional[_NameHit]:
    lines = row.ocr_text if isinstance(row.ocr_text, list) else []
    payload: dict[str, Any] = {}
    if lines:
        payload = vd.vessel_ocr_from_candidate_list(lines, image_id=getattr(row, "id", ""))
    elif vd.is_cover_image_row(row):
        raw = _run_ocr_on_row(row)
        if raw:
            payload = raw
            row.ocr_text = [
                {"text": c["text"], "confidence": c["confidence"]}
                for c in raw.get("candidates", [])
            ]
            row.vessel_guess = raw.get("best_guess") or ""

    if not payload:
        return None

    resolved = auto_resolve_single(payload.get("vessel_ocr") or payload, fleet)
    if not resolved.display_name or resolved.match_kind == "no_nameplate":
        return None

    return _NameHit(
        display=resolved.display_name,
        raw=resolved.raw_ocr or resolved.display_name,
        confidence=resolved.confidence,
        score=resolved.score,
        image_id=getattr(row, "id", "") or "",
        is_cover=vd.is_cover_image_row(row),
        match_kind=resolved.match_kind,
    )


def _merge_clusters(hits: list[_NameHit]) -> list[list[_NameHit]]:
    clusters: list[list[_NameHit]] = []
    for hit in hits:
        placed = False
        for cluster in clusters:
            if _names_same_cluster(hit.display, cluster[0].display):
                cluster.append(hit)
                placed = True
                break
        if not placed:
            clusters.append([hit])
    return clusters


def _best_display(cluster: list[_NameHit]) -> str:
    return max(cluster, key=lambda h: (len(h.display), h.score)).display


def auto_discover_from_images(
    image_rows: list[Any],
    fleet: Optional[list[vessel_reg.VesselEntry]] = None,
    *,
    pinned_name: str = "",
) -> AutoVesselBatchResult:
    """
    Pick vessel name + cover ``image_id`` from a mixed upload batch (fully automated).
    """
    fleet = fleet or []
    out = AutoVesselBatchResult(image_count=len(image_rows))

    if (pinned_name or "").strip():
        pinned = pinned_name.strip()
        cover = vd.pick_photographic_cover_image(
            image_rows, preferred_id=None, vessel_name=pinned,
        )
        if cover:
            hit = _hit_from_row(cover, fleet)
            if hit and vd.names_match(hit.display, pinned):
                return AutoVesselBatchResult(
                    display_name=pinned,
                    match_kind="auto",
                    confidence=hit.confidence,
                    score=hit.score,
                    raw_ocr=hit.raw,
                    cover_image_id=cover.id,
                    image_count=len(image_rows),
                    nameplate_count=1,
                )
        return AutoVesselBatchResult(
            display_name=pinned,
            match_kind="pinned",
            confidence=1.0,
            score=1.0,
            raw_ocr=pinned,
            cover_image_id=cover.id if cover else None,
            image_count=len(image_rows),
        )

    hits: list[_NameHit] = []
    for row in image_rows:
        hit = _hit_from_row(row, fleet)
        if hit:
            hits.append(hit)

    out.nameplate_count = len(hits)
    if not hits:
        out.needs_review = True
        out.review_reason = "No vessel name detected on nameplate photos — set cover manually"
        return out

    clusters = _merge_clusters(hits)

    def cluster_weight(cluster: list[_NameHit]) -> float:
        w = 0.0
        for h in cluster:
            boost = 2.5 if h.is_cover else 1.0
            w += h.score * boost
        return w

    best_cluster = max(clusters, key=cluster_weight)
    display = _best_display(best_cluster)
    cover_pool = [h for h in best_cluster if h.is_cover] or best_cluster
    cover_hit = max(cover_pool, key=lambda h: h.score)

    out_candidates = []
    for c in sorted(clusters, key=cluster_weight, reverse=True)[:6]:
        c_cover = [h for h in c if h.is_cover] or c
        best_h = max(c_cover, key=lambda h: h.score)
        out_candidates.append({
            "name": _best_display(c),
            "votes": len(c),
            "weight": round(cluster_weight(c), 3),
            "cover_image_id": best_h.image_id,
        })

    weak = cover_hit.confidence < _AUTO_MIN_CONF
    out.display_name = display
    out.match_kind = best_cluster[0].match_kind if fleet else "auto"
    out.confidence = cover_hit.confidence
    out.score = cover_hit.score
    out.raw_ocr = cover_hit.raw
    out.cover_image_id = cover_hit.image_id
    out.candidates = out_candidates
    out.needs_review = len(clusters) > 1 or weak
    if len(clusters) > 1:
        alts = ", ".join(_best_display(c) for c in clusters[:3])
        out.review_reason = f"Multiple vessels in upload ({alts}) — confirm correct one"
    elif weak:
        out.review_reason = "Low OCR confidence — confirm vessel name"

    return out


def list_cover_alternates(
    image_rows: list[Any],
    fleet: Optional[list[vessel_reg.VesselEntry]] = None,
    *,
    refresh_ocr: bool = False,
) -> list[dict[str, Any]]:
    """
    All nameplate / whole-ship photos in the batch, one OCR result per image,
    best spelling first — used by UI "Try next nameplate".
    """
    fleet = fleet or []
    coverish = [
        r for r in image_rows
        if vd.is_cover_image_row(r) or (getattr(r, "stage", "") or "") == "not_hull"
    ]
    if refresh_ocr:
        for row in coverish:
            _run_ocr_on_row(row)

    by_id: dict[str, _NameHit] = {}
    for row in coverish:
        hit = _hit_from_row(row, fleet)
        if not hit or not hit.image_id:
            continue
        prev = by_id.get(hit.image_id)
        if prev is None or hit.score > prev.score or (
            hit.score >= prev.score * 0.95 and len(hit.display) > len(prev.display)
        ):
            by_id[hit.image_id] = hit

    hits = list(by_id.values())
    if not hits:
        return []

    global_best = max(
        hits,
        key=lambda h: (len(_cluster_key(h.display)), h.score, h.confidence),
    )
    best_key = _cluster_key(global_best.display)

    def _rank_hit(h: _NameHit) -> tuple:
        hk = _cluster_key(h.display)
        same_vessel = (
            hk == best_key
            or hk in best_key
            or best_key in hk
            or _names_same_cluster(h.display, global_best.display)
        )
        trunc = (
            len(hk) < len(best_key)
            and _share_suffix(h.display, global_best.display)
        )
        return (
            1 if same_vessel and not trunc else 0,
            1 if hk == best_key else 0,
            h.score,
            len(h.display),
            h.confidence,
        )

    ordered = sorted(hits, key=_rank_hit, reverse=True)
    return [
        {
            "image_id": h.image_id,
            "display_name": h.display,
            "confidence": round(h.confidence, 4),
            "score": round(h.score, 4),
            "raw_ocr": h.raw,
            "matches_best_name": _names_same_cluster(h.display, global_best.display),
            "likely_truncated": (
                len(_cluster_key(h.display)) < len(best_key)
                and _share_suffix(h.display, global_best.display)
            ),
        }
        for h in ordered
    ]


def ensure_cover_image_with_ocr(
    images: list[Any],
    *,
    vessel_name: str = "",
    preferred_id: str | None = None,
) -> Optional[Any]:
    """
    Resolve photographic cover for PDF/UI.

    Runs OCR on cover / not_hull shots when ``vessel_guess`` is missing, then
    re-picks so name-only reports (e.g. SILVERSTONE typed manually) still get a photo.
    """
    vn = (vessel_name or "").strip()
    picked = vd.pick_photographic_cover_image(
        images, preferred_id=preferred_id, vessel_name=vn or None,
    )
    if picked is not None:
        return picked

    coverish = [
        i for i in images
        if vd.is_cover_image_row(i) or (getattr(i, "stage", "") or "") == "not_hull"
    ]
    if not coverish:
        return None

    for row in coverish:
        if not (getattr(row, "vessel_guess", "") or "").strip():
            _run_ocr_on_row(row)

    return vd.pick_photographic_cover_image(
        images, preferred_id=preferred_id, vessel_name=vn or None,
    )


def batch_result_to_resolution(batch: AutoVesselBatchResult) -> dict[str, Any]:
    return {
        "display_name": batch.display_name,
        "match_kind": batch.match_kind,
        "confidence": batch.confidence,
        "score": batch.score,
        "raw_ocr": batch.raw_ocr,
        "cover_image_id": batch.cover_image_id,
        "registry_id": batch.registry_id,
        "needs_review": batch.needs_review,
        "review_reason": batch.review_reason or "",
        "alternatives": batch.candidates,
        "image_count": batch.image_count,
        "nameplate_count": batch.nameplate_count,
    }
