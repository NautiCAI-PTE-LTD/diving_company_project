"""Underwater inspection PDF — client format (BW BIRCH / marine survey style).

Sections A–G matching the confidential marine survey template:
  A) General details
  B) Operational details
  C) Summary of works carried out
  D) Hull fouling assessment  (S/G/B codes + severity + %)
  E) Anti-fouling assessment
  F) Hull appendages assessment
  G) Photographs — **before cleaning only**

Branding: company / NautiCAI logo only (no third-party partner names).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .. import config
from . import executive_summary as exec_summary_svc
from . import narrative as narrative_svc
from . import pdf_extract as extract_svc
from . import pdf_report as base
from .birch_reference_data import (
    BIRCH_ANTIFOULING,
    BIRCH_APPENDAGES,
    BIRCH_HULL_FOULING,
    birch_marine_pdf_settings,
    is_birch_report,
    report_company_name,
    strip_partner_text,
)

# Re-use tuned helpers from the legacy marine report builder.
_safe_image = base._safe_image
_photo_grid = base._photo_grid
_chk = base._chk
_yn = base._yn
_draw_logo = base._draw_logo
_kv_table = base._kv_table

ASSETS_DIR = config.BACKEND_DIR / "assets" / "report"
NAUTICAI_LOGO = config.PROJECT_ROOT / "image.png"

# Palette — printable white document (matches reference tables)
INK = colors.HexColor("#1e293b")
GREY_HDR = colors.HexColor("#e2e8f0")
GREY_ROW = colors.HexColor("#f8fafc")
GRID = colors.HexColor("#94a3b8")
BRAND = colors.HexColor("#0891b2")
ACCENT = colors.HexColor("#2563eb")

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "UWT", parent=_styles["Title"], fontName="Helvetica-Bold",
    fontSize=16, leading=20, textColor=INK, spaceAfter=4,
)
H1 = ParagraphStyle(
    "UWH1", parent=_styles["Normal"], fontName="Helvetica-Bold",
    fontSize=11, leading=14, textColor=INK, spaceBefore=8, spaceAfter=4,
)
BODY = ParagraphStyle(
    "UWB", parent=_styles["Normal"], fontName="Helvetica",
    fontSize=9, leading=12, textColor=INK,
)
BODY_B = ParagraphStyle("UWBB", parent=BODY, fontName="Helvetica-Bold")
SMALL = ParagraphStyle("UWS", parent=BODY, fontSize=7.5, leading=10, textColor=INK)
CAPTION = ParagraphStyle("UWC", parent=BODY, fontSize=8, alignment=TA_CENTER, textColor=INK)
CELL = ParagraphStyle(
    "UCell", parent=BODY, fontSize=8, leading=10, textColor=ACCENT,
    fontName="Helvetica-Bold",
)
HDR = ParagraphStyle(
    "UWHdr", parent=BODY_B, fontSize=8, leading=10, alignment=TA_CENTER, textColor=INK,
)
LBL_CELL = ParagraphStyle(
    "LblC", parent=BODY_B, fontSize=8, leading=10, alignment=TA_CENTER, textColor=INK,
)
VAL_CELL = ParagraphStyle(
    "ValC", parent=BODY, fontSize=9, leading=11, alignment=TA_CENTER,
    textColor=ACCENT, fontName="Helvetica-Bold",
)
COVER_TITLE = ParagraphStyle(
    "CovT", parent=TITLE, fontSize=14, leading=18, alignment=TA_CENTER, spaceAfter=4,
)
COVER_SUB = ParagraphStyle(
    "CovS", parent=BODY, fontSize=10, leading=13, alignment=TA_CENTER, textColor=INK,
)
BOX_BG = colors.HexColor("#e8e8e8")
BORDER_BLUE = colors.HexColor("#1e3a8a")

# Reference defaults for BW BIRCH demo / regeneration from source PDF
BIRCH_VESSEL_DEFAULTS: Dict[str, Any] = {
    "vesselType": "LPG TANKER",
    "loa": "225m x 36m",
    "draft": "7.5 m",
    "location": "Fujairah, UAE",
    "diveDate": "13/06/2024",
    "weather": "Fair",
    "sea": "Fair",
    "visibility": "Satisfactory",
    "jobScope": "UW Inspection, UW Hull Cleaning & Propeller Polishing",
    "extra": {
        "grt": "47386",
        "draft_fwd": "--",
        "draft_aft": "7.5 m",
        "current": "--",
        "berthing": "NA",
        "client_rep": "--",
        "surveyor": "NA",
        "class_society": "--",
        "prepared_by": "Ryan Wilson",
        "report_date": "14/06/2024",
        "equipment": (
            "Scuba replacement pack (SRP), underwater CCTV system, Fujifilm underwater "
            "digital camera, HP compressor & hull cleaning equipment's."
        ),
        "mob_day1_from": "13.06.2023/0710Hrs./Fuj Port- Fuj Anch",
        "mob_day1_to": "13.06.2024/1815hrs./ Fuj Anch- Fuj Port",
        "ops_day1_start": "0835hrs/13.06.2024",
        "ops_day1_stop": "1735hrs/13.06.2024",
        "supervisor_1": "Vikram Singh",
        "supervisor_2": "Randeep",
        "divers_list": "Abhay, Pardeep, Jerin, Pawan",
        "works_remarks": (
            "Underwater Hull Inspection, Full Hull Cleaning & Propeller Polishing was carried out."
        ),
    },
}

_TOC_ENTRIES = [
    ("A) GENERAL DETAILS", "3"),
    ("B) OPERATIONAL DETAILS", "3"),
    ("C) SUMMARY WORKS CARRIED OUT", "3"),
    ("D) HULL FOULING ASSESSMENT", "4"),
    ("E) ANTI-FOULING ASSESSMENT", "4"),
    ("F) HULL APPENDAGES ASSESSMENT", "5"),
    ("G) PHOTOGRAPHS", "9"),
]
_TOC_SUB = [
    "a) Bilge Keel", "b) Sea Chest Gratings", "c) Cathodic Protection System",
    "d) Stern Frame Area", "e) Rope Guard", "f) Propeller", "g) Rudder",
]

_SPECIES_CODE = {
    "slime": "S",
    "algae": "A",
    "grass": "G",
    "macroalgae": "G",
    "barnacles": "B",
    "mussels": "M",
    "tubeworms": "T",
    "goosenecks": "GN",
    "calcareous": "CD",
    "mixed_fouling": "O",
    "clean_paint": "",
    "vessel_cover": "",
}
_SEV_CODE = {"A": "L", "B": "M", "C": "H", "D": "VL"}

# (area label, sub-area, region_id for AI cluster — None → NA)
_HULL_GROUPS: List[Tuple[str, List[Tuple[str, Optional[str]]]]] = [
    ("BOW", [
        ("Port", "Bow"), ("Starboard", "Bow"), ("Bottom", "Bow"), ("Thruster/s", None),
    ]),
    ("FORWARD", [
        ("Port", "Verticle_Slide"), ("Starboard", "Verticle_Slide"), ("Bottom", "Flat_bottom"),
    ]),
    ("MIDSHIP", [
        ("Port", "Verticle_Slide"), ("Starboard", "Verticle_Slide"), ("Bottom", "Flat_bottom"),
    ]),
    ("AFT", [
        ("Port", "Verticle_Slide"), ("Starboard", "Verticle_Slide"), ("Bottom", "Flat_bottom"),
    ]),
    ("BILGE KEELS", [("Port", "Bilege_keels"), ("Starboard", "Bilege_keels")]),
    ("INTAKE GRIDS", [
        ("Port", "Sea_chest"), ("Starboard", "Sea_chest"), ("EFP", "Sea_chest"),
    ]),
    ("PROPELLER", [("Blade", "Propeller"), ("Boss Cone", "Propeller")]),
    ("RUDDER", [("—", "Radder")]),
]

_AF_LOCATIONS = [
    "BOW", "PORT VERTICAL", "STBD VERTICAL", "FLAT BOTTOM", "INTAKE GRIDS", "RUDDER",
]

_PHOTO_SECTIONS = [
    ("Bow — Pre-Cleaning", ["Bow"]),
    ("Vertical Sides — Pre-Cleaning", ["Verticle_Slide"]),
    ("Flat Bottom — Pre-Cleaning", ["Flat_bottom"]),
    ("Bilge Keels — Pre-Cleaning", ["Bilege_keels"]),
    ("Sea Chest / Intake Grids — Pre-Cleaning", ["Sea_chest"]),
    ("Propeller — Pre-Cleaning", ["Propeller"]),
    ("Rudder — Pre-Cleaning", ["Radder"]),
    ("Stern / Rope Guard — Pre-Cleaning", ["stren", "Rope"]),
]

# When embedding photos from a source PDF, skip post-cleaning pages unless asked.
_POST_MARKERS = ("Post Cleaning", "Post Polishing", "After Cleaning", "After Polishing")


def _meta(clusters: dict, region_id: Optional[str]) -> dict:
    if not region_id:
        return {}
    bucket = clusters.get(region_id) or {}
    return dict(bucket.get("_meta") or {})


def _fouling_triplets(meta: dict, max_n: int = 3) -> List[str]:
    """Format up to 3 cells like S/H/90%."""
    if not meta or not meta.get("count"):
        return ["", "", ""]
    counts: Dict[str, int] = dict(meta.get("species_counts") or {})
    n = max(int(meta.get("count") or 0), 1)
    ranked = sorted(
        ((k, v) for k, v in counts.items() if k != "clean_paint" and v > 0),
        key=lambda kv: -kv[1],
    )
    out: List[str] = []
    for sp, cnt in ranked[:max_n]:
        code = _SPECIES_CODE.get(sp, "O")
        if not code:
            continue
        pct = round(100.0 * cnt / n)
        sev = narrative_svc.severity_letter(pct, sp)
        out.append(f"{code}/{_SEV_CODE.get(sev, 'M')}/{pct}%")
    while len(out) < max_n:
        out.append("")
    return out


def _condition_pair(findings: dict) -> Tuple[str, str]:
    overall = (findings.get("overall_condition") or "Good").strip().title()
    hull = overall if overall in ("Good", "Fair", "Poor") else "Good"
    paint = "Poor" if findings.get("damage_observed") else (
        "Fair" if hull == "Good" else hull
    )
    return hull, paint


def _x_mark(active: bool) -> str:
    return "<b>X</b>" if active else ""


def _logo_paths(settings: dict) -> Tuple[Optional[Path], Path]:
    """Header logo (company upload or NautiCAI) + footer NautiCAI mark."""
    custom = Path(settings.get("company_logo_path") or "")
    if custom.exists():
        header = custom
    elif NAUTICAI_LOGO.exists():
        header = NAUTICAI_LOGO
    else:
        header = None
    footer = NAUTICAI_LOGO if NAUTICAI_LOGO.exists() else (header or NAUTICAI_LOGO)
    return header, footer


def _make_on_page(settings: dict, vessel_name: str, job_no: str,
                  client_company: str, job_scope: str):
    company = report_company_name(settings)
    header_logo, footer_logo = _logo_paths(settings)
    client = (client_company or "").strip().upper()
    title = (job_scope or "UW Inspection, Hull Cleaning & Propeller Polishing").upper()

    def on_page(canvas, doc):
        canvas.saveState()
        w, h = A4
        top = h - 12 * mm

        if header_logo:
            _draw_logo(canvas, header_logo, 12 * mm, top - 10 * mm, 22 * mm, 10 * mm)
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(38 * mm, top - 4 * mm, company[:42])
        canvas.setFont("Helvetica", 7)
        canvas.drawString(38 * mm, top - 8 * mm, title[:65])

        if client:
            canvas.setFont("Helvetica-Bold", 10)
            canvas.drawRightString(w - 12 * mm, top - 4 * mm, client[:48])
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawRightString(w - 12 * mm, top - 9 * mm,
                               f"Vessel: {(vessel_name or '—')[:36]}")
        canvas.drawRightString(w - 12 * mm, top - 13 * mm,
                               f"Job: {(job_no or '—')[:28]}")

        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.4)
        canvas.line(12 * mm, top - 15 * mm, w - 12 * mm, top - 15 * mm)

        # Footer — powered by
        canvas.setFillColor(GREY_HDR)
        canvas.rect(0, 0, w, 11 * mm, fill=1, stroke=0)
        x = 12 * mm
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(x, 4 * mm, "Powered by")
        x += 16 * mm
        if footer_logo and Path(footer_logo).exists():
            _draw_logo(canvas, footer_logo, x, 1.5 * mm, 14 * mm, 8 * mm)
        canvas.drawRightString(w - 12 * mm, 4 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return on_page


def _make_on_cover(settings: dict):
    """Cover page: logos only in flowable; minimal footer."""

    def on_cover(canvas, doc):
        canvas.saveState()
        w, _h = A4
        _header_logo, footer_logo = _logo_paths(settings)
        canvas.setFillColor(GREY_HDR)
        canvas.rect(0, 0, w, 10 * mm, fill=1, stroke=0)
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(12 * mm, 3.5 * mm, "Powered by")
        x = 28 * mm
        if footer_logo and Path(footer_logo).exists():
            _draw_logo(canvas, footer_logo, x, 1.2 * mm, 12 * mm, 7 * mm)
        canvas.restoreState()

    return on_cover


def _merge_birch_defaults(vessel: dict) -> dict:
    """Fill missing fields from BW BIRCH reference when regenerating that report."""
    v = dict(vessel)
    if "BIRCH" not in (v.get("vesselName") or "").upper():
        return v
    for k, val in BIRCH_VESSEL_DEFAULTS.items():
        if k == "extra":
            ex = dict(v.get("extra") or {})
            for ek, ev in (val or {}).items():
                ex.setdefault(ek, ev)
            v["extra"] = ex
        elif not v.get(k):
            v[k] = val
    return v


def _resolve_cover_image(
    vessel_image_path: Optional[str],
    source_pdf: Optional[Path],
) -> Optional[str]:
    if vessel_image_path and Path(vessel_image_path).exists():
        return vessel_image_path
    cached = config.BACKEND_DIR / "assets" / "report" / "birch_cover_vessel.jpg"
    if cached.exists():
        return str(cached)
    if source_pdf:
        p = extract_svc.extract_cover_vessel_image(source_pdf)
        if p and p.exists():
            return str(p)
    return None


def _cover_page_flow(
    story: list,
    *,
    settings: dict,
    vname: str,
    job_scope: str,
    location: str,
    dive_date: str,
    cover_image_path: Optional[str],
) -> None:
    header_logo, _ = _logo_paths(settings)
    if header_logo:
        story.append(_safe_image(header_logo, 70 * mm, 22 * mm))
        story.append(Spacer(1, 6))

    scope_line = (
        f"Job Scope – {job_scope} at {location} on {dive_date}"
        if location or dive_date
        else f"Job Scope – {job_scope}"
    )
    title_box = Table([
        [Paragraph(f"Underwater Final Report – {vname}", COVER_TITLE)],
        [Paragraph(scope_line, COVER_SUB)],
    ], colWidths=[174 * mm])
    title_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BOX_BG),
        ("BOX", (0, 0), (-1, -1), 1, INK),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(title_box)
    story.append(Spacer(1, 8))

    if cover_image_path:
        img = _safe_image(cover_image_path, 155 * mm, 95 * mm)
        if img:
            framed = Table([[img]], colWidths=[157 * mm])
            framed.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 2.5, BORDER_BLUE),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(framed)


def _table_of_contents(story: list) -> None:
    story.append(Paragraph("<b>Table of Contents</b>", TITLE))
    story.append(Spacer(1, 8))
    rows = []
    for title, pg in _TOC_ENTRIES:
        dots = "." * max(4, 72 - len(title) - len(pg))
        rows.append([Paragraph(title, BODY), Paragraph(dots + " " + pg, BODY)])
    toc = Table(rows, colWidths=[120 * mm, 54 * mm])
    toc.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(toc)
    story.append(Spacer(1, 6))
    for sub in _TOC_SUB:
        story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{sub}", SMALL))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>G) PHOTOGRAPHS</b> &nbsp; … &nbsp; 9 Onwards", BODY))


def _grid_table(rows: list, col_widths) -> Table:
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 0), (0, -1), GREY_HDR),
        ("BACKGROUND", (2, 0), (2, -1), GREY_HDR),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _four_col_row(l1: str, v1: str, l2: str, v2: str) -> list:
    return [
        Paragraph(l1, LBL_CELL), Paragraph(str(v1), VAL_CELL),
        Paragraph(l2, LBL_CELL), Paragraph(str(v2), VAL_CELL),
    ]


def _section_a_general(vessel: dict, extra: dict, vname: str) -> list:
    flow = [_section_title("A) GENERAL DETAILS"), Spacer(1, 4)]
    rows = [
        _four_col_row("VESSEL NAME", vname, "VESSEL TYPE", vessel.get("vesselType") or "—"),
        _four_col_row("SEA STATE", vessel.get("sea") or extra.get("sea_state") or "—",
                      "GRT (T)", extra.get("grt") or "—"),
        _four_col_row("CURRENT", extra.get("current") or "—",
                      "LOA (m)", vessel.get("loa") or "—"),
        _four_col_row("UW VISIBILITY", vessel.get("visibility") or "—",
                      "DRAFT FWD (m)", extra.get("draft_fwd") or "—"),
        _four_col_row("WEATHER", vessel.get("weather") or "—",
                      "DRAFT AFT (m)", extra.get("draft_aft") or vessel.get("draft") or "—"),
    ]
    flow.append(_grid_table(rows, [40 * mm, 47 * mm, 40 * mm, 47 * mm]))
    return flow


def _section_b_operational(vessel: dict, extra: dict, crews: list) -> list:
    flow = [_section_title("B) OPERATIONAL DETAILS"), Spacer(1, 4)]

    admin = _grid_table([
        _four_col_row("BERTHING TO QUAY", extra.get("berthing") or "NA",
                      "CLIENT REP.", extra.get("client_rep") or "—"),
        _four_col_row("ATTENDING SURVEYOR", extra.get("surveyor") or "NA",
                      "CLASS", extra.get("class_society") or "—"),
    ], [40 * mm, 47 * mm, 40 * mm, 47 * mm])
    flow.append(admin)
    flow.append(Spacer(1, 6))

    mob_head = [
        [Paragraph("<b>DETAILS</b>", LBL_CELL), Paragraph("<b>From: MOBILIZATION DATE/TIME/PLACE</b>", HDR),
         Paragraph("<b>To: DEMOBILIZATION DATE/TIME/PLACE</b>", HDR)],
    ]
    for d in (1, 2, 3):
        fk, tk = f"mob_day{d}_from", f"mob_day{d}_to"
        mob_head.append([
            Paragraph(f"Day {d}", LBL_CELL),
            Paragraph(extra.get(fk) or "—", VAL_CELL),
            Paragraph(extra.get(tk) or "—", VAL_CELL),
        ])
    mob = Table(mob_head, colWidths=[28 * mm, 73 * mm, 73 * mm])
    mob.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), GREY_HDR),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(mob)
    flow.append(Spacer(1, 6))

    flow.append(Paragraph("<b>TIME ON SITE:</b>", BODY_B))
    ops_head = [
        [Paragraph("<b>DETAILS</b>", LBL_CELL), Paragraph("<b>OPS STARTED</b>", HDR),
         Paragraph("<b>OPS STOPPED</b>", HDR),
         Paragraph("<b>STAND BY</b>", HDR), Paragraph("<b>REASON FOR REMOBALIZE</b>", HDR)],
    ]
    for d in (1, 2, 3):
        ops_head.append([
            Paragraph(f"Day {d}", LBL_CELL),
            Paragraph(extra.get(f"ops_day{d}_start") or "—", VAL_CELL),
            Paragraph(extra.get(f"ops_day{d}_stop") or "—", VAL_CELL),
            Paragraph(extra.get(f"ops_day{d}_standby") or "—", VAL_CELL),
            Paragraph(extra.get(f"ops_day{d}_remob") or "—", VAL_CELL),
        ])
    ops = Table(ops_head, colWidths=[22 * mm, 38 * mm, 38 * mm, 38 * mm, 38 * mm])
    ops.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), GREY_HDR),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(ops)
    flow.append(Spacer(1, 6))

    flow.append(Paragraph("<b>DIVING TEAM:</b>", BODY_B))
    c0 = crews[0] if crews else {}
    sup1 = extra.get("supervisor_1") or c0.get("supervisor") or "—"
    sup2 = extra.get("supervisor_2") or "—"
    divers = extra.get("divers_list") or c0.get("divers") or "—"
    diver_lines = ", ".join(d.strip() for d in divers.replace("\n", ",").split(",") if d.strip())
    team = Table([
        [Paragraph("<b>SUPERVISOR -1</b>", LBL_CELL),
         Paragraph("<b>SUPERVISOR -2 / ASST. SUPERVISOR / LEAD DIVER</b>", LBL_CELL)],
        [Paragraph(sup1, VAL_CELL), Paragraph(sup2, VAL_CELL)],
        [Paragraph("<b>DIVERS</b>", LBL_CELL), Paragraph(diver_lines, VAL_CELL)],
    ], colWidths=[87 * mm, 87 * mm])
    team.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), GREY_HDR),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    flow.append(team)
    flow.append(Spacer(1, 6))

    equip = extra.get("equipment") or (
        "Scuba replacement pack (SRP), underwater CCTV system, underwater digital camera, "
        "HP compressor & hull cleaning equipment."
    )
    eq_box = Table([
        [Paragraph("<b>EQUIPMENT USED:</b>", BODY_B)],
        [Paragraph(equip, BODY)],
    ], colWidths=[174 * mm])
    eq_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow.append(eq_box)
    return flow


def _section_c_works(vessel: dict, extra: dict, clusters: dict,
                      region_inspections: dict) -> list:
    flow = [_section_title("C) SUMMARY — WORKS CARRIED OUT"), Spacer(1, 4)]
    flow.append(Paragraph(
        "THIS IS TO CERTIFY THAT THE FOLLOWING HAS BEEN SATISFACTORILY COMPLETED "
        "AS FAR AS CAN BE ASCERTAINED:", SMALL))
    flow.append(Spacer(1, 4))
    flow.append(_works_summary(clusters, region_inspections))
    flow.append(Spacer(1, 6))
    rem = Table([
        [Paragraph("<b>REMARKS:</b>", BODY_B)],
        [Paragraph(extra.get("works_remarks") or vessel.get("notes") or "—", BODY)],
        [Paragraph(
            f"<b>REPORT PREPARED BY:</b> {extra.get('prepared_by') or '—'} &nbsp;&nbsp;&nbsp; "
            f"<b>DATE:</b> {extra.get('report_date') or vessel.get('diveDate') or '—'}",
            BODY)],
    ], colWidths=[174 * mm])
    rem.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow.append(rem)
    return flow


def _section_title(text: str) -> Paragraph:
    return Paragraph(f"<b>{text}</b>", H1)


def _hull_fouling_table(
    clusters: dict,
    region_inspections: dict,
    vessel: Optional[dict] = None,
) -> Table:
    use_birch = vessel is not None and is_birch_report(vessel)
    legend = Paragraph(
        "<b>FOULING TYPE:</b> S-Slime, G-Grass, T-Tubeworm, B-Barnacles, GN-Goosenecks, "
        "M-Mussels, C-Coral, EB-Expanding bryozoans, CD-Calcium Deposits, O-Other &nbsp;|&nbsp; "
        "<b>SEVERITY:</b> VL-Very Light, L-Light, M-Moderate, H-Heavy &nbsp;|&nbsp; "
        "<i>Example: S/M/10%; B/M-H/40%</i>",
        SMALL,
    )

    head1 = [
        Paragraph("AREAS", HDR),
        Paragraph("Sub-area", HDR),
        Paragraph("FOULING / SEVERITY / PERCENTAGE (%)", HDR),
        "", "",
        Paragraph("GENERAL CONDITION<br/>(Good / FAIR / POOR)", HDR),
        "",
    ]
    head2 = [
        "", "",
        Paragraph("FOULING 1", HDR),
        Paragraph("FOULING 2", HDR),
        Paragraph("FOULING 3", HDR),
        Paragraph("HULL", HDR),
        Paragraph("PAINT", HDR),
    ]
    data: list = [head1, head2]
    spans: list = []

    row_i = 2
    for area, subs in _HULL_GROUPS:
        start = row_i
        for j, (sub, rid) in enumerate(subs):
            ref = BIRCH_HULL_FOULING.get((area, sub)) if use_birch else None
            meta = _meta(clusters, rid) if rid else {}
            use_ref = bool(ref and use_birch and not meta.get("count"))
            if use_ref:
                cells = [ref["f1"], ref["f2"], ref["f3"]]
                hull, paint = ref["hull"], ref["paint"]
            elif rid is None:
                cells = ["NA", "", ""]
                hull, paint = "NA", "NA"
            else:
                meta = _meta(clusters, rid)
                cells = _fouling_triplets(meta)
                findings = region_inspections.get(rid) or {}
                hull, paint = _condition_pair(findings)
                if not cells[0] and not meta.get("count"):
                    cells, hull, paint = ["—", "", ""], "—", "—"
            data.append([
                Paragraph(area, BODY_B) if j == 0 else "",
                Paragraph(sub, BODY),
                Paragraph(cells[0] or "—", CELL),
                Paragraph(cells[1] or "", CELL),
                Paragraph(cells[2] or "", CELL),
                Paragraph(hull, BODY),
                Paragraph(paint, BODY),
            ])
            row_i += 1
        if len(subs) > 1:
            spans.append(("SPAN", (0, start), (0, row_i - 1)))

    t = Table(data, colWidths=(22 * mm, 24 * mm, 28 * mm, 28 * mm, 28 * mm, 22 * mm, 22 * mm))
    style = [
        ("BACKGROUND", (0, 0), (-1, 1), GREY_HDR),
        ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
        ("SPAN", (2, 0), (4, 0)),
        ("SPAN", (5, 0), (6, 0)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (4, -1), "CENTER"),
        ("ALIGN", (5, 0), (6, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_ROW]),
    ]
    for cmd in spans:
        style.append(cmd)
    t.setStyle(TableStyle(style))

    wrapper = Table([[legend], [t]], colWidths=[174 * mm])
    wrapper.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return wrapper


def _anti_fouling_table(vessel: dict, region_inspections: dict) -> list:
    extra = vessel.get("extra") or {}
    use_birch = is_birch_report(vessel)
    coating_spc = extra.get("coating_spc", True)
    coating_non = extra.get("coating_non_spc", False)
    remarks = extra.get("paint_remarks") or (
        "Overall paint condition was Fair to Good."
    )

    coat = Table([[
        Paragraph("<b>COATING TYPE</b>", BODY_B),
        Paragraph(f"{_chk(coating_spc)} SPC (Self Polishing Coat)", BODY),
        Paragraph(f"{_chk(coating_non)} NON-SPC", BODY),
    ]], colWidths=(40 * mm, 70 * mm, 64 * mm))

    defects = Paragraph(
        "<b>PAINT DEFECTS:</b> (1) PEELING (2) BLISTERING (3) CRACKING (4) CORROSION "
        "(5) MECHANICAL DAMAGE (6) COLD FLOW (7) GROUNDING (8) DETACHMENT",
        SMALL,
    )

    head = [
        Paragraph("LOCATION", HDR),
        Paragraph("TYPE", HDR),
        Paragraph("% AREA", HDR),
        Paragraph("GOOD", HDR),
        Paragraph("FAIR", HDR),
        Paragraph("POOR", HDR),
    ]
    rows = [head]
    if use_birch:
        af_rows = BIRCH_ANTIFOULING
    else:
        paint_map = extra.get("paint_condition_by_location") or {}
        af_rows = [
            {"location": loc, **paint_map.get(loc, {})}
            for loc in _AF_LOCATIONS
        ]
    for pc in af_rows:
        loc = pc.get("location", "")
        g = pc.get("good", False)
        f = pc.get("fair", False)
        p = pc.get("poor", False)
        rows.append([
            Paragraph(loc, BODY),
            Paragraph(str(pc.get("type", "") or ""), BODY),
            Paragraph(str(pc.get("pct", "") or ""), BODY),
            Paragraph(_x_mark(g), BODY),
            Paragraph(_x_mark(f), BODY),
            Paragraph(_x_mark(p), BODY),
        ])

    tbl = Table(rows, colWidths=(38 * mm, 18 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm))
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREY_HDR),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_ROW]),
    ]))

    rem = Table([[Paragraph(f"<b>REMARKS:</b> {remarks}", BODY)]], colWidths=[174 * mm])
    return [coat, Spacer(1, 4), defects, Spacer(1, 4), tbl, Spacer(1, 6), rem]


def _works_summary(clusters: dict, region_inspections: dict) -> Table:
    def has_region(*ids: str) -> bool:
        for rid in ids:
            b = clusters.get(rid) or {}
            if b.get("_meta", {}).get("count", 0) > 0:
                return True
            if region_inspections.get(rid, {}).get("inspection_done"):
                return True
        return False

    def cleaned(*ids: str) -> bool:
        for rid in ids:
            if (clusters.get(rid) or {}).get("after"):
                return True
        return False

    items = [
        ("PHOTOGRAPHIC", True),
        ("CCTV / Post Cleaning", False),
        ("CCTV CLASS", False),
        ("STBD SIDE", True),
        ("PORT SIDE", True),
        ("FLAT BOTTOM", True),
        ("BILGE KEELS", True),
        ("RUDDER", True),
        ("SEA CHESTS", True),
        ("POLISHING", True),
        ("CLEANING", False),
        ("GRINDING", False),
        ("COFFERDAM", False),
        ("BLANKING/ PLUGGING", False),
        ("WELDING", False),
        ("TRANSDUCER", False),
    ]
    rows = []
    for label, done in items:
        rows.append([Paragraph(f"{_chk(done)} {label}", BODY)])
    t = Table(rows, colWidths=[174 * mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _executive_paragraph(clusters: dict) -> str:
    """Narrative opener from AI clusters (shared with marine/BIRCH builders)."""
    return exec_summary_svc.inspection_summary_paragraph(clusters)


def _photo_grid_from_paths(paths: List[str], thumb_w: float = 54 * mm,
                          thumb_h: float = 40 * mm, cols: int = 3,
                          photos: Optional[List[dict]] = None):
    if photos:
        imgs = [p for p in photos if Path(p.get("path", "")).exists()]
    else:
        imgs = [{"path": p} for p in paths if Path(p).exists()]
    if not imgs:
        return Paragraph("<i>— no photographs —</i>", SMALL)
    return _photo_grid(imgs, thumb_w=thumb_w, thumb_h=thumb_h, cols=cols)


def _section_base(title: str) -> str:
    """Merge '… Pre-Cleaning' with '… Pre-Cleaning (Midship to AFT)'."""
    t = title.replace("\ufffd", "–").strip()
    return re.sub(r"\s*\([^)]*\)\s*$", "", t).strip() or t


def _merge_photo_sections(sections: List[dict]) -> List[dict]:
    merged: List[dict] = []
    for block in sections:
        title = (block.get("title") or "Photographs").replace("\ufffd", "–")
        paths = list(block.get("paths") or [])
        base = _section_base(title)
        if merged and _section_base(merged[-1]["title"]) == base:
            merged[-1]["paths"].extend(paths)
            if "(" in title and "(" not in merged[-1]["title"]:
                merged[-1]["title"] = title
        else:
            merged.append({"title": title, "paths": paths})
    return merged


def _photos_from_source_pdf(story: list, source_pdf: Path, *,
                            before_only: bool = False) -> bool:
    """Append section G from all photos embedded in *source_pdf*."""
    manifest = extract_svc.extract_pdf_photos(source_pdf)
    sections = extract_svc.merge_photo_sections(manifest)
    if not sections:
        return False

    any_added = False
    for block in sections:
        title = block.get("title") or "Photographs"
        if before_only and any(m in title for m in _POST_MARKERS):
            continue
        photos = [p for p in (block.get("photos") or []) if Path(p.get("path", "")).exists()]
        if not photos and block.get("paths"):
            photos = [{"path": p, "caption": title} for p in block["paths"] if Path(p).exists()]
        if not photos:
            continue
        any_added = True
        story.append(Paragraph(title, BODY_B))
        story.append(Paragraph(extract_svc.section_description(title), SMALL))
        story.append(_photo_grid_from_paths([], photos=photos))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.3, color=GRID, spaceAfter=6))

    if any_added:
        story.append(Paragraph(
            f"<i>Photographs extracted from source document ({len(manifest.get('images') or [])} images).</i>",
            SMALL,
        ))
    return any_added


def _photos_from_clusters(story: list, clusters: dict, *,
                          before_only: bool = True) -> bool:
    any_photos = False
    for section_title, region_ids in _PHOTO_SECTIONS:
        imgs: list = []
        for rid in region_ids:
            bucket = clusters.get(rid) or {}
            imgs.extend(bucket.get("before") or [])
            if not before_only:
                imgs.extend(bucket.get("after") or [])
        if not imgs:
            continue
        cap = config.PDF_MAX_PHOTOS_PER_STAGE
        if cap > 0:
            imgs = base.sample_report_photos(imgs, cap * (2 if not before_only else 1))
        any_photos = True
        story.append(Paragraph(section_title, BODY_B))
        story.append(_photo_grid(imgs, thumb_w=54 * mm, thumb_h=40 * mm, cols=3))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.3, color=GRID, spaceAfter=6))
    return any_photos


def _rubert_scale_table(title: str, pre: List[str], post: List[str]) -> Table:
    blades = ["1", "2", "3", "4", "5", "6"]
    head = [Paragraph("<b>BLADE</b>", HDR)] + [Paragraph(b, HDR) for b in blades]
    rows = [
        head,
        [Paragraph("<b>PRE-CLEAN</b>", LBL_CELL)]
        + [Paragraph(pre[i] if i < len(pre) else "NA", VAL_CELL) for i in range(6)],
        [Paragraph("<b>POST-CLEAN</b>", LBL_CELL)]
        + [Paragraph(post[i] if i < len(post) else "NA", VAL_CELL) for i in range(6)],
    ]
    t = Table(rows, colWidths=[22 * mm] + [25 * mm] * 6)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREY_HDR),
        ("BOX", (0, 0), (-1, -1), 0.5, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    wrap = Table([[Paragraph(f"<b>{title}</b>", BODY_B)], [t]], colWidths=[174 * mm])
    return wrap


def _appendages_section_birch() -> list:
    """Section F — full BW BIRCH reference content."""
    d = BIRCH_APPENDAGES
    flow: list = [_section_title("F) HULL APPENDAGES ASSESSMENT"), Spacer(1, 4)]

    bk = d["bilge_keels"]
    flow.append(Paragraph("<b>a) BILGE KEELS</b>", BODY_B))
    flow.append(_kv_table([
        ("TYPE", f"{_chk(not bk['type_split'])} SINGLE &nbsp; {_chk(bk['type_split'])} SPLIT"),
        ("NO. OF SECTIONS", bk["sections"]),
    ], col_widths=(50 * mm, 120 * mm)))
    flow.append(_grid_table([
        _four_col_row("PORT — INDENTATION", _yn(not bk["port_indent"]),
                      "PORT — CRACKS ON WELD", _yn(bk["port_cracks"])),
        _four_col_row("PORT — ANODES FITTED", bk["port_anodes"],
                      "ANODES % REMAINING", bk["port_anode_pct"]),
        _four_col_row("STBD — INDENTATION", _yn(not bk["stbd_indent"]),
                      "STBD — CRACKS ON WELD", _yn(bk["stbd_cracks"])),
        _four_col_row("STBD — ANODES FITTED", bk["stbd_anodes"],
                      "ANODES % REMAINING", bk["stbd_anode_pct"]),
    ], [40 * mm, 47 * mm, 40 * mm, 47 * mm]))
    flow.append(Spacer(1, 6))

    sc = d["sea_chest"]
    flow.append(Paragraph("<b>b) SEA CHEST GRATINGS</b>", BODY_B))
    flow.append(Paragraph(
        f"SECURING: {_chk(sc['securing']=='swing')} SWING DOOR &nbsp; "
        f"{_chk(sc['securing']=='welded')} WELDED &nbsp; {_chk(sc['securing']=='bolted')} BOLTED<br/>"
        f"CONDITION: {_chk(sc['condition_good'])} GOOD &nbsp; {_chk(not sc['condition_good'])} DEFECTIVE &nbsp; "
        f"NUTS/WIRES: {_chk(sc['nuts_intact'])} INTACT &nbsp; {_chk(not sc['nuts_intact'])} NOT INTACT",
        BODY))
    flow.append(_grid_table([
        _four_col_row("TOTAL GRATINGS", sc["total"], "ON PORT", sc["port"]),
        _four_col_row("ON STBD", sc["stbd"], "ON BOTTOM / EFP", f"{sc['bottom']} / {sc['efp']}"),
    ], [40 * mm, 47 * mm, 40 * mm, 47 * mm]))
    flow.append(Spacer(1, 6))

    cp = d["cathodic"]
    flow.append(Paragraph("<b>c) CATHODIC PROTECTION SYSTEM</b>", BODY_B))
    flow.append(_kv_table([
        ("ICCP", f"{_chk(cp['iccp_yes'])} YES &nbsp; {_chk(not cp['iccp_yes'])} NO"),
        ("Visible damage", f"{_chk(cp['damage'])} YES &nbsp; {_chk(not cp['damage'])} NO"),
        ("ICCP anodes fitted", cp["anodes"]),
        ("REMARKS", cp["remarks"]),
    ], col_widths=(45 * mm, 125 * mm)))
    flow.append(Spacer(1, 6))

    sf = d["stern_frame"]
    flow.append(Paragraph("<b>d) STERN FRAME AREA</b>", BODY_B))
    flow.append(Paragraph(
        f"CASTING: {_chk(sf['casting_good'])} GOOD {_chk(not sf['casting_good'])} DEFECTIVE &nbsp; "
        f"RUDDER WELDS: {_chk(sf['rudder_weld_good'])} GOOD &nbsp; "
        f"HULL WELDS: {_chk(sf['hull_weld_good'])} GOOD &nbsp; "
        f"DAMAGE: {_chk(sf['damage'])} YES {_chk(not sf['damage'])} NO",
        BODY))
    flow.append(Spacer(1, 6))

    rg = d["rope_guard"]
    flow.append(Paragraph("<b>e) ROPE GUARD</b>", BODY_B))
    flow.append(Paragraph(
        f"CONDITION: {_chk(rg['condition_good'])} GOOD &nbsp; "
        f"SECURING: {_chk(rg['securing_welded'])} WELDED &nbsp; "
        f"ROPE CUTTERS: {_chk(rg['rope_cutters'])} YES &nbsp; "
        f"DAMAGE: {_chk(rg['damage'])} YES {_chk(not rg['damage'])} NO",
        SMALL))
    flow.append(Spacer(1, 6))

    pr = d["propeller"]
    flow.append(Paragraph("<b>f) PROPELLER</b>", BODY_B))
    flow.append(_grid_table([
        _four_col_row("DIAMETER (mm)", pr["diameter"], "NO. OF BLADES", pr["blades"]),
    ], [40 * mm, 47 * mm, 40 * mm, 47 * mm]))
    flow.append(Paragraph(
        f"TYPE: {_chk(pr['conventional'])} CONVENTIONAL &nbsp; {_chk(pr['cpp'])} CPP &nbsp; "
        f"{_chk(pr['single'])} SINGLE &nbsp; {_chk(pr['twin'])} TWIN",
        SMALL))
    flow.append(Spacer(1, 4))
    flow.append(Paragraph(
        "<b>PRE and POST PROPELLER POLISHING — PRESSURE SIDE (Rubert scale)</b>", BODY_B))
    flow.append(_rubert_scale_table("", pr["pressure_pre"], pr["pressure_post"]))
    flow.append(Spacer(1, 4))
    flow.append(Paragraph("<b>SUCTION SIDE (Rubert scale)</b>", BODY_B))
    flow.append(_rubert_scale_table("", pr["suction_pre"], pr["suction_post"]))
    flow.append(Paragraph(
        f"BLADE: {_chk(pr['blade_good'])} GOOD &nbsp; PITTING: {_yn(pr['pitting'])} &nbsp; "
        f"CAVITATION: {_yn(pr['cavitation'])} &nbsp; REMARKS: {pr['remarks']}",
        SMALL))
    flow.append(Spacer(1, 6))

    ru = d["rudder"]
    flow.append(Paragraph("<b>g) RUDDER</b>", BODY_B))
    flow.append(_kv_table([
        ("TYPE", f"{_chk(ru['type_hanging'])} HANGING"),
        ("PLATE CONDITION", f"{_chk(ru['plate_good'])} GOOD"),
        ("CRACKS", f"{_chk(ru['cracks'])} YES {_chk(not ru['cracks'])} NO"),
        ("RUDDER PLUGS", f"{ru['plugs']} — {_chk(ru['plugs_intact'])} INTACT"),
        ("REMARKS", ru["remarks"]),
    ], col_widths=(45 * mm, 125 * mm)))
    return flow


def _appendages_section(region_inspections: dict,
                        vessel: Optional[dict] = None) -> list:
    if vessel and is_birch_report(vessel):
        return _appendages_section_birch()
    flow: list = [_section_title("F) HULL APPENDAGES ASSESSMENT")]
    bk = (region_inspections.get("Bilege_keels") or {}).get("bilge_keels") or {}
    if bk:
        flow.append(Paragraph("<b>a) BILGE KEELS</b>", BODY_B))
        flow.append(_kv_table([
            ("Port sections", str(bk.get("port_sections") or "—")),
            ("Stbd sections", str(bk.get("stbd_sections") or "—")),
        ], col_widths=(50 * mm, 120 * mm)))
    if not bk:
        flow.append(Paragraph("<i>Complete appendage fields in the app or use BW BIRCH reference.</i>", SMALL))
    return flow



def build_pdf(
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
    """Build the UW inspection PDF (client / BW BIRCH layout)."""
    out_path = Path(out_path)
    created_at = created_at or datetime.utcnow()
    region_inspections = region_inspections or {}
    settings = dict(settings or {})
    settings["exclude_partner_branding"] = True
    settings["company_name"] = report_company_name(settings)
    settings["company_tagline"] = strip_partner_text(settings.get("company_tagline") or "")
    settings["report_footer"] = strip_partner_text(settings.get("report_footer") or "") or "Powered by NautiCAI"
    vessel = _merge_birch_defaults(vessel)
    if is_birch_report(vessel):
        settings = birch_marine_pdf_settings(settings)
    extra = vessel.get("extra") or {}

    vname = vessel.get("vesselName", "") or "—"
    jno = vessel.get("jobNo", "") or "—"
    job_scope = vessel.get("jobScope") or "UW Inspection, Hull Cleaning & Propeller Polishing"
    client_info = vessel.get("client") or {}
    client_company = (client_info.get("company") or "").strip()
    company_name = report_company_name(settings)
    location = vessel.get("location") or "—"
    dive_date = vessel.get("diveDate") or "—"

    source_pdf = extract_svc.resolve_source_pdf(
        vessel, explicit=source_pdf_path or extra.get("source_pdf_path"))
    if source_pdf:
        extract_svc.extract_cover_vessel_image(source_pdf)
    clusters = base.cap_clusters_for_pdf(clusters)
    base.prewarm_cluster_thumbnails(
        clusters,
        thumb_w=54 * mm,
        thumb_h=40 * mm,
        extra_paths=[vessel_image_path] if vessel_image_path else None,
    )
    cover_img = _resolve_cover_image(vessel_image_path, source_pdf)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=18 * mm, bottomMargin=14 * mm,
        title=f"UW Final Report — {vname}",
        author=company_name,
    )
    on_page = _make_on_page(settings, vname, jno, client_company, job_scope)
    on_cover = _make_on_cover(settings)
    story: list = []

    # ---- Page 1: Cover (no narrative summary) ----------------------------
    _cover_page_flow(
        story,
        settings=settings,
        vname=vname,
        job_scope=job_scope,
        location=location,
        dive_date=dive_date,
        cover_image_path=cover_img,
    )
    story.append(PageBreak())

    # ---- Page 2: Table of Contents ---------------------------------------
    _table_of_contents(story)
    story.append(PageBreak())

    # ---- Photographic Report opener (vessel name + OCR cover photo) -------
    base.append_photographic_opener(
        story, vessel=vessel, vessel_image_path=cover_img,
        vname=vname, jno=jno,
    )
    story.append(PageBreak())

    # ---- Page 3: A + B + C (reference layout) ----------------------------
    crews = vessel.get("crews") or []
    if not crews and vessel.get("diveSupervisor"):
        crews = [{
            "supervisor": vessel.get("diveSupervisor"),
            "divers": vessel.get("divers"),
            "boat_captain": vessel.get("boatCaptain"),
            "days": list((extra.get("time_duration") or {}).values()),
        }]
    story.extend(_section_a_general(vessel, extra, vname))
    story.append(Spacer(1, 8))
    story.extend(_section_b_operational(vessel, extra, crews))
    story.append(Spacer(1, 8))
    story.extend(_section_c_works(vessel, extra, clusters, region_inspections))
    story.append(PageBreak())

    # ---- D) Hull fouling --------------------------------------------------
    story.append(_section_title("D) HULL FOULING ASSESSMENT"))
    story.append(Spacer(1, 4))
    story.append(_hull_fouling_table(clusters, region_inspections, vessel))

    story.append(Spacer(1, 10))
    story.append(_section_title("E) ANTI-FOULING ASSESSMENT"))
    story.extend(_anti_fouling_table(vessel, region_inspections))

    story.append(PageBreak())
    story.extend(_appendages_section(region_inspections, vessel))

    # ---- G) Photographs ---------------------------------------------------
    story.append(PageBreak())
    story.append(_section_title("G) PHOTOGRAPHS (Mark Location of Photos)"))
    story.append(Spacer(1, 6))

    before_only = not extra.get("include_post_cleaning_photos", True)

    any_photos = False
    if source_pdf:
        any_photos = _photos_from_source_pdf(
            story, source_pdf, before_only=before_only)
    if not any_photos:
        any_photos = _photos_from_clusters(
            story, clusters, before_only=before_only)
    if not any_photos:
        story.append(Paragraph(
            "<i>No photographs available — upload images or attach a source PDF "
            "(Final Report … .pdf in project root for BW BIRCH).</i>",
            SMALL,
        ))

    # Sign-off
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"<b>Prepared by:</b> {company_name} &nbsp;·&nbsp; "
        f"<b>Report ID:</b> {report_id} &nbsp;·&nbsp; "
        f"<b>Generated:</b> {created_at:%d %b %Y}",
        SMALL,
    ))

    doc.build(story, onFirstPage=on_cover, onLaterPages=on_page)
    return out_path
