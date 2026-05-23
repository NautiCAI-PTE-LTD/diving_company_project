"""Marine PDF: Azolla branding, Birch survey tables, reference photos."""
from datetime import datetime
from pathlib import Path

from backend.services.pdf_extract import default_birch_source_pdf, extract_pdf_photos
from backend.services.pdf_report import build_pdf

src = default_birch_source_pdf()
print("Source PDF:", src)
if src:
    m = extract_pdf_photos(src, force_refresh=False)
    print(f"Photos: {len(m.get('images') or [])} images")

out = Path("backend/storage/reports/_marine_birch_full.pdf")
vessel = {
    "vesselName": "BW BIRCH",
    "vesselType": "LPG TANKER",
    "jobNo": "BIRCH-UWI-2024",
    "jobScope": "UW Inspection",
    "location": "Fujairah, UAE",
    "diveDate": "13/06/2024",
    "diveSupervisor": "Vikram Singh",
    "divers": "Abhay, Pardeep, Jerin, Pawan",
}
settings = {
    "company_name": "NautiCAI",
    "report_footer": "Powered by NautiCAI",
}

build_pdf(
    out,
    vessel=vessel,
    clusters={},
    region_inspections={},
    settings=settings,
    source_pdf_path=str(src) if src else None,
    report_id="NCAI-BIRCH-FULL",
    created_at=datetime.utcnow(),
)
print("Wrote", out, f"({round(out.stat().st_size / 1e6, 2)} MB)")
