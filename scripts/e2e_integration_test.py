"""
End-to-end: species model + ship-cover gate + report PDF vs reference PDF text.

Usage (repo root):
  python scripts/e2e_integration_test.py
  python scripts/e2e_integration_test.py --vessel PATRIS --max-images 12
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

from backend import config
from backend.db import db_session, init_db, Company, Report, Image as ImageRow, User
from backend.inference import _runtime as inf_runtime
from backend.inference import region, before_after, species
from backend.services import analyze as analyze_svc
from backend.services import cluster as cluster_svc
from backend.services.pdf_report_uw import build_pdf

VESSEL_ROOT = Path(r"D:\test species model\marine_report\data\species_dataset")
REF_PDFS = {
    "PATRIS": VESSEL_ROOT / "2024-1562 Patris, UHI , PP.pdf",
    "Atlanta": VESSEL_ROOT / "2024-1593 ATALANTA.pdf",
    "Photos Dalma": VESSEL_ROOT / "24-1573 DALMA UHI & PP.pdf",
    "SILVERSTONE": VESSEL_ROOT / "2024-1765 SILVERSTONE - COFFERDAM TO BLANK ECGS OB.pdf",
}
SHIP_COVER = Path(r"F:\ship_image")
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _pick_images(vessel: str, max_n: int) -> list[Path]:
    root = VESSEL_ROOT / vessel
    out: list[Path] = []
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in IMG_EXT:
            continue
        out.append(p)
        if len(out) >= max_n:
            break
    return out


def _pdf_species_words(pdf_path: Path) -> set[str]:
    if not pdf_path.is_file():
        return set()
    try:
        import fitz
    except ImportError:
        return set()
    doc = fitz.open(str(pdf_path))
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    found = set()
    for word in ("Slime", "Algae", "Grass", "Barnacles", "Mussels", "Tube", "Clean"):
        if re.search(rf"\b{re.escape(word)}", text, re.I):
            found.add(word.lower())
    return found


def _ensure_company() -> str:
    init_db()
    with db_session() as s:
        co = s.query(Company).first()
        if co is None:
            co = Company(
                id="e2e-co",
                name="NautiCAI E2E Test",
                email="e2e@test.local",
                tagline="Integration test",
            )
            s.add(co)
            s.add(
                User(
                    id="e2e-user",
                    email="e2e@test.local",
                    password_hash="x",
                    company_id=co.id,
                    role="admin",
                )
            )
        return co.id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vessel", default="PATRIS")
    ap.add_argument("--max-images", type=int, default=10)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "backend" / "storage" / "reports" / "_e2e_test")
    args = ap.parse_args()

    print("=== Model backends ===")
    for ckpt in (config.SHIP_REGION_CKPT, config.SPECIES_CKPT, config.BEFORE_AFTER_CKPT):
        ch = inf_runtime.resolve(ckpt)
        print(f"  {ckpt.name}: {ch.backend} ({ch.reason})")
    print(f"  Species classes: {species.class_names()}")
    print(f"  Ship cover dir: {config.SHIP_COVER_REFERENCE_DIR}")

    # Warmup
    species.predict(Image.new("RGB", (224, 224), (50, 80, 60)))

    hull_paths = _pick_images(args.vessel, args.max_images)
    cover_path = None
    if SHIP_COVER.is_dir():
        for p in sorted(SHIP_COVER.glob("*.JPG"))[:1]:
            cover_path = p
            break

    if not hull_paths:
        print("WARN: no underwater hull images picked — loosen filters or check vessel path")
    print(f"\n=== Analyze {len(hull_paths)} hull + cover={cover_path is not None} ===")

    company_id = _ensure_company()
    image_ids: list[str] = []
    cover_id: str | None = None
    species_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    rows_out: list[dict] = []

    all_paths = list(hull_paths)
    if cover_path:
        all_paths.insert(0, cover_path)

    for path in all_paths:
        iid = uuid.uuid4().hex[:12]
        dest = ROOT / "backend" / "storage" / "uploads" / f"{iid}{path.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        r = analyze_svc.analyze_file(dest, original_filename=path.name, image_id=iid)
        with db_session() as s:
            row = s.get(ImageRow, iid)
            if row:
                row.company_id = company_id
        if r.get("cover_only") or r.get("ship_cover_reference"):
            cover_id = iid
        else:
            species_counts[r["species"]["top"]] += 1
            stage_counts[r["stage"]["id"]] += 1
        image_ids.append(iid)
        rows_out.append(
            {
                "file": path.name,
                "cover_only": r.get("cover_only"),
                "region": r["region"]["id"],
                "stage": r["stage"]["id"],
                "species": r["species"]["top"],
                "species_display": r["species"].get("top_display"),
                "fouling_pct": r.get("fouling_pct"),
                "ocr": (r.get("vessel_ocr") or {}).get("best_guess"),
            }
        )
        print(
            f"  {path.name[:40]:40s}  cover={r.get('cover_only')}  "
            f"reg={r['region']['id'][:12]:12s}  stage={r['stage']['id']:6s}  "
            f"sp={r['species']['top']:12s} ({r['species'].get('top_display', '')})"
        )

    rep_id = f"E2E-{args.vessel[:6].upper()}-{uuid.uuid4().hex[:6]}"
    with db_session() as s:
        rep = Report(
            id=rep_id,
            company_id=company_id,
            vessel_name=args.vessel,
            vessel_type="Cargo",
            job_no=f"E2E-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            job_scope="UW Inspection E2E",
            location="Test",
            status="draft",
            vessel_image_id=cover_id,
        )
        s.add(rep)
        for iid in image_ids:
            row = s.get(ImageRow, iid)
            if row:
                row.report_id = rep.id
        clusters = cluster_svc.cluster_images(rep.images)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        pdf_out = args.out_dir / f"{rep_id}.pdf"
        build_pdf(
            pdf_out,
            vessel={
                "vesselName": args.vessel,
                "vesselType": "Cargo",
                "jobNo": rep.job_no,
                "jobScope": rep.job_scope,
                "location": rep.location,
            },
            clusters=clusters,
            region_inspections={},
            vessel_image_path=(
                str(s.get(ImageRow, cover_id).path) if cover_id and s.get(ImageRow, cover_id) else None
            ),
            settings={"company_name": "NautiCAI E2E", "report_footer": "E2E test"},
            report_id=rep_id,
            created_at=datetime.now(timezone.utc),
        )
        rep.pdf_path = str(pdf_out)
        rep.status = "completed"

    ref_pdf = REF_PDFS.get(args.vessel)
    ref_words = _pdf_species_words(ref_pdf) if ref_pdf else set()

    report = {
        "report_id": rep_id,
        "pdf": str(pdf_out),
        "hull_images": len(hull_paths),
        "cover_image": str(cover_path) if cover_path else None,
        "species_on_hull": dict(species_counts),
        "stage_on_hull": dict(stage_counts),
        "reference_pdf": str(ref_pdf) if ref_pdf else None,
        "reference_pdf_mentions": sorted(ref_words),
        "analyses": rows_out,
    }
    json_path = args.out_dir / f"{rep_id}_summary.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n=== Done ===")
    print(f"PDF: {pdf_out}")
    print(f"Summary: {json_path}")
    print(f"Hull species counts: {dict(species_counts)}")
    print(f"Reference PDF species words: {sorted(ref_words)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
