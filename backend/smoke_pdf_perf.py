"""Generate PDF for the most recent report twice and report wall-clock.

The first call populates the thumbnail cache; the second call should be
visibly faster because every photo is served from cache instead of
re-encoded from disk.
"""
from __future__ import annotations
import sys, time, io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception: pass

from backend import config
from backend.db import db_session, Report, Image as ImageRow, Company
from backend.services import pdf_report as pdf_svc
from backend.services import cluster as cluster_svc
from backend.services import storage as storage_svc
from backend.main import _db_to_vessel

with db_session() as s:
    rep = s.query(Report).order_by(Report.created_at.desc()).first()
    if not rep:
        print("No reports in DB — create one in the UI first.")
        sys.exit(0)
    rid = rep.id
    print(f"Using report {rid} · vessel={rep.vessel_name}")

    clusters = cluster_svc.cluster_images(rep.images)
    vessel_image_path = None
    if rep.vessel_image_id:
        vi = s.get(ImageRow, rep.vessel_image_id)
        if vi and Path(vi.path).exists():
            vessel_image_path = vi.path
    c = s.get(Company, rep.company_id)
    settings_dict = {
        "company_name": c.name if c else "",
        "company_tagline": c.tagline if c else "",
        "company_address": c.address if c else "",
        "company_phone": c.phone if c else "",
        "company_email": c.email if c else "",
        "company_website": c.website if c else "",
        "company_logo_path": c.logo_path if c else None,
        "report_footer": c.report_footer if c else "",
        "country": c.country if c else "",
        "registration_number": c.registration_number if c else "",
        "tax_number": c.tax_number if c else "",
        "class_approvals": list(c.class_approvals or []) if c else [],
        "diving_certifications": c.diving_certifications if c else "",
        "insurance": c.insurance if c else "",
        "report_prefix": (c.report_prefix if c else "NAUTICAI-REP") or "NAUTICAI-REP",
        "established_year": c.established_year if c else None,
    }
    vessel_dict = _db_to_vessel(rep).model_dump()
    region_insp = rep.region_inspections or {}
    created_at  = rep.created_at

def run():
    out = storage_svc.report_pdf_path(rid)
    pdf_svc.build_pdf(
        out, vessel=vessel_dict, clusters=clusters,
        region_inspections=region_insp, vessel_image_path=vessel_image_path,
        settings=settings_dict, report_id=rid, created_at=created_at,
    )
    return out.stat().st_size

t = time.perf_counter(); size1 = run(); dt1 = time.perf_counter() - t
t = time.perf_counter(); size2 = run(); dt2 = time.perf_counter() - t
t = time.perf_counter(); size3 = run(); dt3 = time.perf_counter() - t

print(f"  run 1 (cold thumbs)  : {dt1*1000:7.1f} ms   {size1/1024:.1f} KB")
print(f"  run 2 (warm thumbs)  : {dt2*1000:7.1f} ms   {size2/1024:.1f} KB")
print(f"  run 3 (warm thumbs)  : {dt3*1000:7.1f} ms   {size3/1024:.1f} KB")
saved = (1.0 - (dt2 / dt1)) * 100.0
print(f"  speed-up after cache : {saved:5.1f} %")
