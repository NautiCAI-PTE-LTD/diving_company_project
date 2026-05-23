"""
Silverstone end-to-end: analyze hull batch + cover, generate PDF, compare to reference PDF text.

Usage:
  python scripts/silverstone_report_test.py
  python scripts/silverstone_report_test.py --deploy-first
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

VESSEL = "SILVERSTONE"
DATA = Path(r"D:\test species model\marine_report\data\species_dataset") / VESSEL
REF_PDF = DATA.parent / "2024-1765 SILVERSTONE - COFFERDAM TO BLANK ECGS OB.pdf"
SHIP_COVER = Path(r"F:\ship_image")
OUT = ROOT / "backend" / "storage" / "reports" / "_silverstone_test"
IMG_EXT = {".jpg", ".jpeg", ".png"}


def _hull_candidate(_pil: Image.Image) -> bool:
    """Include all images; hull vs cover is decided by models in analyze_file."""
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hull", type=int, default=40)
    ap.add_argument("--deploy-first", action="store_true")
    args = ap.parse_args()

    if args.deploy_first:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "deploy_species_labeled.py")])
        if r.returncode != 0:
            return r.returncode

    from backend import config
    from backend.db import db_session, init_db, Company, Report, Image as ImageRow
    from backend import species_registry as species_reg
    from backend.services import analyze as analyze_svc
    from backend.services import cluster as cluster_svc
    from backend.services.pdf_report_uw import build_pdf

    species_reg.sync_config()
    print("Species model classes:", species_reg.load_class_names())

    hull_paths = []
    for p in sorted(DATA.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXT:
            try:
                if _hull_candidate(Image.open(p).convert("RGB")):
                    hull_paths.append(p)
            except OSError:
                continue
        if len(hull_paths) >= args.max_hull:
            break

    cover = None
    for p in sorted(SHIP_COVER.glob("P321*.JPG")):
        cover = p
        break
    init_db()
    company_id = "silverstone-test"
    with db_session() as s:
        if not s.get(Company, company_id):
            s.add(Company(id=company_id, name="Silverstone Test", email="test@local"))

    image_ids = []
    stats = {"cover": 0, "hull": 0, "species": Counter(), "stage": Counter(), "cover_skipped_ba": 0}

    todo = ([cover] if cover else []) + hull_paths
    print(f"Analyzing {len(todo)} images ({len(hull_paths)} hull + cover)...", flush=True)
    for n, path in enumerate(todo, 1):
        if path is None:
            continue
        print(f"  [{n}/{len(todo)}] {path.name}", flush=True)
        iid = uuid.uuid4().hex[:12]
        dest = ROOT / "backend" / "storage" / "uploads" / f"{iid}{path.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        r = analyze_svc.analyze_file(dest, original_filename=path.name, image_id=iid)
        with db_session() as s:
            row = s.get(ImageRow, iid)
            if row:
                row.company_id = company_id
        image_ids.append(iid)
        if r.get("cover_only"):
            stats["cover"] += 1
            if r.get("fouling_analysis_skipped"):
                stats["cover_skipped_ba"] += 1
        else:
            stats["hull"] += 1
            stats["species"][r["species"]["top"]] += 1
            stats["stage"][r["stage"]["id"]] += 1

    rep_id = f"SS-{uuid.uuid4().hex[:8]}"
    with db_session() as s:
        rep = Report(
            id=rep_id,
            company_id=company_id,
            vessel_name="SILVERSTONE",
            vessel_type="Cargo",
            job_no="E2E-SILVERSTONE",
            job_scope="UW Inspection",
            location="Test",
            status="draft",
        )
        s.add(rep)
        cover_id = None
        for iid in image_ids:
            row = s.get(ImageRow, iid)
            if row:
                row.report_id = rep.id
                if row.region == "vessel_cover" and cover_id is None:
                    cover_id = iid
        rep.vessel_image_id = cover_id
        report_rows = [s.get(ImageRow, iid) for iid in image_ids if s.get(ImageRow, iid)]
        s.commit()
        clusters = cluster_svc.cluster_images(report_rows)
        print(f"Building PDF ({len(report_rows)} images, {len(clusters)} regions)...", flush=True)
        OUT.mkdir(parents=True, exist_ok=True)
        pdf_out = OUT / f"{rep_id}.pdf"
        vi = s.get(ImageRow, cover_id) if cover_id else None
        build_pdf(
            pdf_out,
            vessel={"vesselName": "SILVERSTONE", "vesselType": "Cargo", "jobNo": rep.job_no,
                    "jobScope": rep.job_scope, "location": "Test"},
            clusters=clusters,
            region_inspections={},
            vessel_image_path=str(vi.path) if vi and Path(vi.path).exists() else None,
            settings={"company_name": "NautiCAI", "report_footer": "Silverstone E2E"},
            report_id=rep_id,
            created_at=datetime.now(timezone.utc),
        )
        rep.pdf_path = str(pdf_out)
        s.commit()

    print("Comparing to reference PDF...", flush=True)

    def _pdf_text(path: Path) -> str:
        if not path.is_file():
            return ""
        import fitz
        doc = fitz.open(str(path))
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text

    ref_text = _pdf_text(REF_PDF)
    new_text = _pdf_text(pdf_out)

    species_tokens = (
        "slime", "algae", "grass", "tubeworm", "barnacle", "mussel",
        "gooseneck", "calcareous", "mixed", "clean",
    )
    ref_species = [t for t in species_tokens if re.search(rf"\b{t}", ref_text, re.I)]
    new_species = [t for t in species_tokens if re.search(rf"\b{t}", new_text, re.I)]

    report = {
        "report_id": rep_id,
        "pdf": str(pdf_out),
        "hull_images": stats["hull"],
        "cover_images": stats["cover"],
        "species_hull": dict(stats["species"]),
        "stage_hull": dict(stats["stage"]),
        "reference_pdf": str(REF_PDF),
        "reference_has_fouling_table": bool(re.search(r"Fouling Condition", ref_text, re.I)),
        "new_has_executive_summary": bool(re.search(r"Executive Summary|Fouling Condition", new_text, re.I)),
        "new_has_vessel_name": bool(re.search(r"SILVERSTONE", new_text, re.I)),
        "new_has_photographic_report": bool(re.search(r"Photographic Report", new_text, re.I)),
        "reference_species_mentions": ref_species,
        "new_species_mentions": new_species,
        "cover_skipped_ba": stats.get("cover_skipped_ba", 0),
    }
    (OUT / f"{rep_id}_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
