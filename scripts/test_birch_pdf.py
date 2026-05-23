"""Build UW report PDF with all photos extracted from the BW BIRCH reference."""
from datetime import datetime
from pathlib import Path

from backend.services.pdf_extract import default_birch_source_pdf, extract_pdf_photos
from backend.services.pdf_report_uw import build_pdf

src = default_birch_source_pdf()
print("source:", src)
m = extract_pdf_photos(src, force_refresh=True)
print("sections:", len(m["sections"]), "images:", len(m["images"]))
for s in m["sections"]:
    print(f"  {len(s['paths']):3d}  {s['title'][:70]}")

out = Path("backend/storage/reports/_birch_with_photos.pdf")
vessel = {
    "vesselName": "BW BIRCH",
    "vesselType": "LPG TANKER",
    "jobNo": "BIRCH-REF",
    "jobScope": "UW Inspection, Hull Cleaning & Propeller Polishing",
    "location": "Fujairah, UAE",
    "diveDate": "13/06/2024",
    "loa": "225m x 36m",
    "extra": {"grt": "47386", "use_birch_reference": True},
}
build_pdf(
    out,
    vessel=vessel,
    clusters={},
    region_inspections={},
    settings={"company_name": "NautiCAI"},
    report_id="birch-full",
    created_at=datetime.utcnow(),
    source_pdf_path=str(src),
)
print("PDF:", out, "MB:", round(out.stat().st_size / 1e6, 2))
