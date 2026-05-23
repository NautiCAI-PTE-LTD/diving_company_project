"""BW BIRCH marine report builder (NautiCAI layout + reference PDF data/photos)."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import logging
import tempfile

from .. import config

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Flowable

from . import pdf_report as R
from . import pdf_extract as extract_svc
from . import executive_summary as exec_summary_svc
from .birch_reference_data import (
    BIRCH_SUMMARY_WORKS,
    birch_marine_pdf_settings,
    is_birch_report,
    merge_birch_vessel,
    report_company_name,
)
from .pdf_report_uw import _hull_fouling_table, _anti_fouling_table

log = logging.getLogger("nauticai.pdf.birch")


class PageAnchor(Flowable):
    def __init__(self, key: str, registry: Dict[str, int]):
        self.key = key
        self.registry = registry

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        self.registry[self.key] = self.canv.getPageNumber()


def _anchor(key: str, registry: Dict[str, int]) -> list:
    return [PageAnchor(key, registry)]


def _toc_spec(has_notes: bool) -> list[tuple[str, str]]:
    spec = [
        ("General Information", "toc_general"),
        ("Diving Team & Sea Conditions", "toc_diving"),
        ("Equipment Used", "toc_equipment"),
        ("Summary of Works Done", "toc_summary"),
        ("UW Hull Inspection & Cleaning Summary", "toc_uw_summary"),
        ("Hull Fouling Assessment", "toc_hull_fouling"),
        ("Anti-Fouling Assessment", "toc_antifouling"),
        ("Fouling Conditions Executive Summary", "toc_executive"),
        ("Photographic Report", "toc_photos"),
    ]
    if has_notes:
        spec.append(("Remarks", "toc_remarks"))
    spec.append(("Sign-Off", "toc_signoff"))
    return spec


def _toc_table(story: list, spec: list[tuple[str, str]], page_map: Dict[str, str]) -> None:
    story.append(Paragraph("Table of Contents", R.H_TITLE))
    story.append(Spacer(1, 10))
    rows = []
    for title, key in spec:
        pg = page_map.get(key, "—")
        dots = "." * max(6, 68 - len(title) - len(str(pg)))
        rows.append([Paragraph(title, R.BODY), Paragraph(f"{dots} {pg}", R.BODY)])
    toc = Table(rows, colWidths=[125 * mm, 49 * mm])
    toc.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(toc)
    story.append(PageBreak())


def _birch_on_page(settings: dict, vessel_name: str, job_no: str, job_scope: str):
    """NautiCAI logo header; sub-bar shows Job No. only."""
    logo = Path(settings.get("company_logo_path") or R.NAUTICAI_LOGO)
    if not logo.exists():
        logo = R.NAUTICAI_LOGO
    title = (job_scope or "UW Inspection").upper()
    footer = settings.get("report_footer") or "Powered by NautiCAI"
    client = ((settings.get("client_company") or "") or "").strip()

    def on_page(canvas, doc):
        canvas.saveState()
        w, h = A4
        banner_h = 22 * mm
        sub_h = 6 * mm

        canvas.setFillColor(R.INK_900)
        canvas.rect(0, h - banner_h, w, banner_h, fill=1, stroke=0)
        if logo.exists():
            R._draw_logo(canvas, logo, 12 * mm, h - banner_h + 3.5 * mm, 28 * mm, 14 * mm)
        canvas.setFillColor(R.colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawRightString(w - 12 * mm, h - 11 * mm, title[:70])
        canvas.setFillColor(R.BRAND_L)
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(w - 12 * mm, h - 15 * mm, "Marine Service Report")

        canvas.setFillColor(R.GREY_100)
        canvas.rect(0, h - banner_h - sub_h, w, sub_h, fill=1, stroke=0)
        canvas.setFillColor(R.INK_900)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(12 * mm, h - banner_h - sub_h + 1.8 * mm, "Job No.:  ")
        canvas.setFillColor(R.BRAND)
        canvas.drawString(32 * mm, h - banner_h - sub_h + 1.8 * mm, (job_no or "—")[:36])

        canvas.setFillColor(R.INK_700)
        canvas.rect(0, 0, w, 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(R.colors.white)
        canvas.setFont("Helvetica", 7)
        if client:
            canvas.drawString(12 * mm, 4.5 * mm, f"Client: {client[:48]}")
        canvas.drawRightString(w - 12 * mm, 4.5 * mm, footer[:40])
        canvas.drawRightString(w - 12 * mm, 8.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return on_page


def _summary_table_birch() -> Table:
    head = [
        Paragraph("<b>Areas</b>", R.BODY_B),
        Paragraph("<b>Inspected</b>", R.BODY_B),
        Paragraph("<b>Cleaned</b>", R.BODY_B),
    ]
    rows = [head]
    for label, inspected, cleaned in BIRCH_SUMMARY_WORKS:
        rows.append([
            Paragraph(label, R.BODY),
            Paragraph(R._chk(inspected), R.BODY),
            Paragraph(R._chk(cleaned), R.BODY),
        ])
    t = Table(rows, colWidths=(110 * mm, 30 * mm, 30 * mm), repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), R.INK_700),
        ("TEXTCOLOR", (0, 0), (-1, 0), R.colors.white),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.4, R.INK_500),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, R.GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [R.colors.white, R.GREY_50]),
    ]))
    return t


def _executive_table_birch(clusters: Dict[str, Any]) -> Table:
    """AI-driven executive summary (same logic as marine template)."""
    return exec_summary_svc.build_executive_summary_table(
        clusters,
        body_style=R.BODY,
        body_bold_style=R.BODY_B,
        small_style=R.SMALL,
        head_style=R.BODY_B,
        header_bg=R.HEADER_FG,
        row_alt=R.GREY_50,
    )


def _append_body(
    story: list,
    *,
    vessel: dict,
    clusters: dict,
    region_inspections: dict,
    settings: dict,
    report_id: str,
    created_at: datetime,
    company_name: str,
    job_scope: str,
    vname: str,
    jno: str,
    source_pdf: Optional[Path],
    vessel_image_path: Optional[str] = None,
    page_registry: Optional[Dict[str, int]] = None,
    toc_page_map: Optional[Dict[str, str]] = None,
    skip_toc: bool = False,
) -> None:
    extra = vessel.get("extra") or {}
    client_info = vessel.get("client") or {}
    has_notes = bool(vessel.get("notes"))
    toc_spec = _toc_spec(has_notes)

    def mark(key: str) -> None:
        if page_registry is not None:
            story.extend(_anchor(key, page_registry))

    # Cover (no vessel photo / no prepared-by line)
    title = job_scope.title() if job_scope else "Marine Service Report"
    story.append(Paragraph(title, R.H_TITLE))
    story.append(Paragraph(
        f"Report ID <b>{report_id}</b> &nbsp;·&nbsp; "
        f"Created {created_at:%d %b %Y, %H:%M UTC}",
        R.H_SUB,
    ))
    story.append(PageBreak())

    if not skip_toc:
        _toc_table(story, toc_spec, toc_page_map or {})

    mark("toc_general")
    story.append(R._section_header("GENERAL INFORMATION"))
    g_left = R._kv_table([
        ("Date of Dive", vessel.get("diveDate", "")),
        ("Job No.", vessel.get("jobNo", "")),
        ("Vessel Name", vessel.get("vesselName", "")),
        ("Vessel Type", vessel.get("vesselType", "")),
        ("Vessel Class", vessel.get("vesselClass", "")),
    ], col_widths=(34 * mm, 56 * mm))
    g_right_rows = [
        ("Job Scope", vessel.get("jobScope", "")),
        ("Location", vessel.get("location", "")),
        ("LOA (m)", vessel.get("loa", "")),
        ("Vessel Draft", vessel.get("draft", "")),
        ("Captain (Vessel)", vessel.get("captain", "")),
    ]
    if extra.get("grt"):
        g_right_rows.insert(2, ("GRT (T)", extra["grt"]))
    story.append(R._two_cols(g_left, R._kv_table(g_right_rows, col_widths=(34 * mm, 56 * mm))))

    crews = vessel.get("crews") or []
    for idx, c in enumerate(crews, 1):
        if idx == 1:
            mark("toc_diving")
        label = (c.get("label") or f"Diving Team - {idx}").upper()
        story.append(R._section_header(label))
        story.append(R._kv_table([
            ("Dive Supervisor", c.get("supervisor", "")),
            ("Divers and Tenders", c.get("divers", "")),
            ("Boat Captain", c.get("boat_captain", "")),
        ], col_widths=(48 * mm, 130 * mm)))
        sea = c.get("sea") or {}
        story.append(Spacer(1, 2))
        story.append(Paragraph("<b>SEA CONDITIONS</b>", R.H2))
        story.append(R._two_cols(
            R._kv_table([("Weather", sea.get("weather", "")), ("Sea", sea.get("sea", ""))],
                        col_widths=(38 * mm, 52 * mm)),
            R._kv_table([("Visibility (m)", sea.get("visibility", "")),
                         ("Tide (kn)", sea.get("tide", ""))],
                        col_widths=(38 * mm, 52 * mm)),
        ))
        for d_idx, d in enumerate(c.get("days") or [], 1):
            day_title = f"TIME AND DURATION OF JOB — Day {d_idx}"
            if d.get("date"):
                day_title += f" &nbsp;·&nbsp; {d['date']}"
            story.append(Spacer(1, 2))
            story.append(Paragraph(f"<b>{day_title}</b>", R.H2))
            story.append(R._kv_table([
                ("Time Left Base", d.get("time_left_base", "")),
                ("Time Arrived Job Site", d.get("time_arrived_jobsite", "")),
                ("Dive Ops Started", d.get("dive_ops_started", "")),
                ("Dive Ops Completed", d.get("dive_ops_completed", "")),
                ("Time Left Job Site", d.get("time_left_jobsite", "")),
                ("Time Arrived Base", d.get("time_arrived_base", "")),
            ], col_widths=(55 * mm, 110 * mm)))

    if extra.get("equipment"):
        mark("toc_equipment")
        story.append(R._section_header("EQUIPMENT USED"))
        story.append(Paragraph(extra["equipment"], R.BODY))
        story.append(Spacer(1, 4))

    story.append(PageBreak())
    mark("toc_summary")
    story.append(R._section_header("SUMMARY OF WORKS DONE"))
    story.append(_summary_table_birch())
    story.append(Spacer(1, 6))
    if extra.get("works_remarks"):
        story.append(Paragraph(f"<b>Remarks:</b> {extra['works_remarks']}", R.BODY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "We hereby confirm that the above works have been completed with safety.", R.BODY))
    story.append(Spacer(1, 14))
    sup_table = Table([
        [Paragraph("<b>Dive Supervisor:</b>", R.LBL), Paragraph(vessel.get("diveSupervisor", ""), R.BODY),
         Paragraph("<b>Date:</b>", R.LBL), Paragraph(vessel.get("diveDate", ""), R.BODY)],
    ], colWidths=(34 * mm, 70 * mm, 18 * mm, 50 * mm))
    story.append(sup_table)

    story.append(PageBreak())
    mark("toc_uw_summary")
    story.append(R._section_header("UW HULL INSPECTION & CLEANING SUMMARY"))
    story.append(Paragraph(
        exec_summary_svc.inspection_summary_paragraph(clusters), R.BODY))
    story.append(Spacer(1, 8))
    mark("toc_hull_fouling")
    story.append(R._section_header("HULL FOULING ASSESSMENT"))
    story.append(Spacer(1, 4))
    story.append(_hull_fouling_table(clusters, region_inspections, vessel))
    story.append(PageBreak())
    mark("toc_antifouling")
    story.append(R._section_header("ANTI-FOULING ASSESSMENT"))
    story.extend(_anti_fouling_table(vessel, region_inspections))
    story.append(PageBreak())

    mark("toc_executive")
    story.append(R._section_header("FOULING CONDITIONS EXECUTIVE SUMMARY"))
    story.append(exec_summary_svc.build_executive_header(
        vessel.get("vesselName", ""), vessel.get("jobNo", ""), body_style=R.BODY))
    story.append(Spacer(1, 3))
    story.append(exec_summary_svc.build_species_legend_table(
        clusters, small_style=R.SMALL, default_band_bg=R.BRAND_L))
    story.append(Spacer(1, 4))
    story.append(_executive_table_birch(clusters))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>Severity:</b> &nbsp;(A) Light &nbsp;·&nbsp; (B) Moderate &nbsp;·&nbsp; "
        "(C) Heavy &nbsp;·&nbsp; (D) Clean", R.SMALL))
    story.append(Paragraph(
        "<i>Descriptions and thickness ranges are inferred from AI image analysis "
        "(per-region species classification and visual coverage) — estimates from "
        "your uploaded photographs, not copied from a reference PDF.</i>", R.SMALL))

    story.append(PageBreak())
    mark("toc_photos")
    R.append_photographic_opener(
        story, vessel=vessel, vessel_image_path=vessel_image_path,
        vname=vname, jno=jno,
    )
    if source_pdf:
        R._append_photos_from_source_pdf(story, source_pdf)

    if has_notes:
        mark("toc_remarks")
        story.append(R._section_header("REMARKS"))
        story.append(Paragraph(vessel["notes"].replace("\n", "<br/>"), R.BODY))

    mark("toc_signoff")
    story.append(Spacer(1, 8))
    story.append(R._section_header("SIGN-OFF"))
    sig = Table([
        [Paragraph("<b>Dive Supervisor</b>", R.LBL),
         Paragraph("<b>Captain (Vessel)</b>", R.LBL),
         Paragraph("<b>Client Representative</b>", R.LBL)],
        [Paragraph(vessel.get("diveSupervisor", "_______________________"), R.BODY),
         Paragraph(vessel.get("captain", "_______________________"), R.BODY),
         Paragraph("_______________________", R.BODY)],
    ], colWidths=(60 * mm, 60 * mm, 60 * mm))
    story.append(sig)


def build_birch_marine_pdf(
    out_path: Path, *,
    vessel: dict,
    clusters: dict,
    region_inspections: Optional[Dict[str, Any]] = None,
    vessel_image_path: Optional[str] = None,
    source_pdf_path: Optional[str] = None,
    settings: Optional[dict] = None,
    report_id: str,
    created_at: Optional[datetime] = None,
) -> Path:
    out_path = Path(out_path)
    vessel = merge_birch_vessel(vessel)
    settings = birch_marine_pdf_settings(settings or {})
    company_name = report_company_name(settings)
    region_inspections = region_inspections or {}
    created_at = created_at or datetime.utcnow()
    vname = vessel.get("vesselName", "") or "—"
    jno = vessel.get("jobNo", "") or "—"
    job_scope = vessel.get("jobScope") or "UW Inspection"

    clusters = R.cap_clusters_for_pdf(clusters)
    R.prewarm_cluster_thumbnails(
        clusters,
        extra_paths=[vessel_image_path] if vessel_image_path else None,
    )

    source_pdf = extract_svc.resolve_source_pdf_for_photos(
        vessel, source_pdf_path, clusters=clusters)

    on_page = _birch_on_page(settings, vname, jno, job_scope)
    doc_kw = dict(
        pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=34 * mm, bottomMargin=14 * mm,
        title=f"NautiCAI · Marine Service Report · {vname}",
        author="NautiCAI",
    )

    if config.PDF_BIRCH_SINGLE_PASS:
        log.info("report %s: birch PDF single-pass (fast)", report_id)
        story: list = []
        _append_body(
            story, vessel=vessel, clusters=clusters,
            region_inspections=region_inspections,
            settings=settings, report_id=report_id, created_at=created_at,
            company_name=company_name, job_scope=job_scope, vname=vname, jno=jno,
            source_pdf=source_pdf, vessel_image_path=vessel_image_path,
            toc_page_map={}, skip_toc=False,
        )
        SimpleDocTemplate(str(out_path), **doc_kw).build(
            story, onFirstPage=on_page, onLaterPages=on_page)
        return out_path

    registry: Dict[str, int] = {}
    tmp = Path(tempfile.gettempdir()) / f"nauticai_birch_{report_id}.pdf"
    s1: list = []
    _append_body(
        s1, vessel=vessel, clusters=clusters, region_inspections=region_inspections,
        settings=settings, report_id=report_id, created_at=created_at,
        company_name=company_name, job_scope=job_scope, vname=vname, jno=jno,
        source_pdf=source_pdf, vessel_image_path=vessel_image_path,
        page_registry=registry, skip_toc=True,
    )
    SimpleDocTemplate(str(tmp), **doc_kw).build(
        s1, onFirstPage=on_page, onLaterPages=on_page)

    offset = 1  # TOC page inserted after cover
    toc_pages = {k: str(registry[k] + offset) for _, k in _toc_spec(bool(vessel.get("notes")))
                 if k in registry}

    story = []
    _append_body(
        story, vessel=vessel, clusters=clusters, region_inspections=region_inspections,
        settings=settings, report_id=report_id, created_at=created_at,
        company_name=company_name, job_scope=job_scope, vname=vname, jno=jno,
        source_pdf=source_pdf, vessel_image_path=vessel_image_path,
        toc_page_map=toc_pages, skip_toc=False,
    )
    SimpleDocTemplate(str(out_path), **doc_kw).build(
        story, onFirstPage=on_page, onLaterPages=on_page)
    tmp.unlink(missing_ok=True)
    return out_path


def build_pdf_if_birch(
    out_path: Path, *, vessel: dict, **kwargs: Any,
) -> Optional[Path]:
    if is_birch_report(merge_birch_vessel(vessel)):
        return build_birch_marine_pdf(out_path, vessel=vessel, **kwargs)
    return None
