"""Cluster a report's images by hull region & before/after stage."""
from __future__ import annotations
from collections import defaultdict
from typing import Dict, List
from .. import config
from . import narrative as narrative_svc


# Pseudo-region tags that mean "this is NOT a hull close-up". These images
# are kept on the report (e.g. as the vessel-name cover photo) but excluded
# from the per-region clusters / photo grids / executive summary.
NON_HULL_REGIONS = {"vessel_cover", "overview", ""}


def cluster_images(images) -> Dict[str, Dict[str, List[dict]]]:
    """
    images: iterable of db.Image rows
    Returns: { region_id: { 'before': [...], 'after': [...], '_meta': {...} } }

    Whole-ship overview shots (region == 'vessel_cover') are skipped here —
    they appear only on the report's Photographic Report opener via
    `report.vessel_image_id`, never inside a per-region grid.
    """
    out: Dict[str, Dict[str, List[dict]]] = {}
    for img in images:
        region = (img.region or "").strip()
        if not region or region in NON_HULL_REGIONS:
            continue
        stage = (img.stage or "").strip()
        if stage not in ("before", "after"):
            continue
        bucket = out.setdefault(region, {"before": [], "after": [], "_meta": {
            "region_id": region,
            "region_display": config.HULL_REGION_DISPLAY.get(region, region),
            "count": 0, "avg_fouling": 0.0,
            "species_counts": defaultdict(int),
            "severities": defaultdict(int),
        }})
        bucket[stage].append({
            "id": img.id, "filename": img.filename, "path": img.path,
            "stage": stage, "species_top": img.species_top,
            "fouling_pct": img.fouling_pct, "severity": img.severity,
        })
        meta = bucket["_meta"]
        meta["count"] += 1
        meta["avg_fouling"] += img.fouling_pct or 0.0
        dist = img.species_dist if isinstance(img.species_dist, list) else []
        added = False
        for entry in dist:
            if isinstance(entry, dict):
                sid = entry.get("id") or entry.get("species")
                prob = float(entry.get("prob", 0) or 0)
                if sid and prob > 0.05:
                    meta["species_counts"][sid] = meta["species_counts"].get(sid, 0) + prob
                    added = True
        if not added:
            meta["species_counts"][img.species_top or "unknown"] += 1
        meta["severities"][img.severity or "A"] += 1

    # finalise meta
    for region_id, bucket in out.items():
        m = bucket["_meta"]
        if m["count"] > 0:
            m["avg_fouling"] = round(m["avg_fouling"] / m["count"], 1)
        m["species_counts"] = dict(m["species_counts"])
        m["severities"]     = dict(m["severities"])
        # Thickness range from per-photo AI fouling % + species (averaged), not
        # a single region-mean % pushed through one bracket.
        analysed = bucket["before"] + bucket["after"]
        m["thickness_range"] = narrative_svc.thickness_range_from_analysed_images(
            analysed,
        )
        m["thickness_source"] = "per_image_avg"
        # dominant severity = max severity letter present  (worst case)
        for sev in ("C", "B", "A", "D"):
            if m["severities"].get(sev):
                m["dominant_severity"] = sev
                break
        else:
            m["dominant_severity"] = "A"
    return out


def report_rollup(images) -> dict:
    """Aggregate KPIs for a report."""
    if not images:
        return {"avg_fouling": 0.0, "severity": "A"}
    avg = sum((i.fouling_pct or 0.0) for i in images) / len(images)
    # worst severity wins
    sev_order = {"D": 0, "A": 1, "B": 2, "C": 3}
    worst = "A"
    for i in images:
        if sev_order.get(i.severity or "A", 1) > sev_order.get(worst, 1):
            worst = i.severity
    return {"avg_fouling": round(avg, 1), "severity": worst}
