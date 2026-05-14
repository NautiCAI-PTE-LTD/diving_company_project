"""Generate the Marine Inspection & Analysis Report PDF.

Layout mirrors `marine_service_report (2).pdf` page-by-page:

  Page  1 : Cover — General Info + Client Reps + Diving Team + Sea Conditions
  Page  2 : Time and Duration of Job (Day 1 / Day 2 / Day 3)
  Page  3+: Per-region inspection (one section per hull region)
  Page  N : FOULING CONDITIONS — EXECUTIVE SUMMARY (AI sentences + thickness)
  Page N+1: PHOTOGRAPHIC REPORT cover with vessel-name OCR photo
  Page N+2 …: Per-region Before / After photo grids
  Last    : Sign-off

Branding
  • Client company logo : top-left of every page
  • NautiCAI logo+brand : top-right of every page
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import io

from PIL import Image as PILImage, ImageOps

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, PageBreak,
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.enums import TA_CENTER

from .. import config
from . import narrative as narrative_svc
from . import vessel_diagram as diagram_svc

# -------------------------- brand palette ----------------------------------
# Top banner stays dark so the client brand pops. Everything *below* the
# banner now uses a lighter, calmer palette so the body of the report
# reads like a printable document rather than a dark-mode UI.
INK_900   = colors.HexColor("#0a1429")    # banner background only
INK_700   = colors.HexColor("#152748")    # footer background
INK_500   = colors.HexColor("#2a4575")    # body labels
BRAND     = colors.HexColor("#0891b2")    # cyan accent (links, ticks)
BRAND_D   = colors.HexColor("#0e7490")    # darker brand for accents on white
BRAND_L   = colors.HexColor("#cffafe")    # pale cyan tint
BRAND_LL  = colors.HexColor("#ecfeff")    # very pale cyan (section header bg)
GREY      = colors.HexColor("#e5e7eb")
GREY_50   = colors.HexColor("#f8fafc")
GREY_100  = colors.HexColor("#f1f5f9")
GREY_200  = colors.HexColor("#e5e7eb")
GREY_DARK = colors.HexColor("#475569")    # body text
HEADER_BG = colors.HexColor("#e0f2fe")    # section-header band (sky-100)
HEADER_FG = colors.HexColor("#075985")    # section-header text (sky-800)

NAUTICAI_LOGO = config.PROJECT_ROOT / "image.png"

# -------------------------- styles -----------------------------------------
_styles = getSampleStyleSheet()
H_TITLE = ParagraphStyle("HT", parent=_styles["Title"],
    fontName="Helvetica-Bold", fontSize=18, leading=22,
    textColor=INK_900, spaceAfter=2)
H_SUB   = ParagraphStyle("HS", parent=_styles["Normal"],
    fontName="Helvetica", fontSize=9, textColor=INK_500, spaceAfter=8)
H1      = ParagraphStyle("H1", parent=_styles["Heading1"],
    fontName="Helvetica-Bold", fontSize=11.5, textColor=HEADER_FG,
    backColor=HEADER_BG, leading=15, spaceBefore=10, spaceAfter=8,
    leftIndent=4, rightIndent=4, borderPadding=(5, 5, 5, 5))
H2      = ParagraphStyle("H2", parent=_styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=10.5, textColor=BRAND,
    leading=14, spaceBefore=6, spaceAfter=4)
BODY    = ParagraphStyle("Body", parent=_styles["Normal"],
    fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK_900)
BODY_B  = ParagraphStyle("BodyB", parent=BODY, fontName="Helvetica-Bold")
LBL     = ParagraphStyle("Lbl", parent=BODY,
    fontName="Helvetica-Bold", textColor=INK_500, fontSize=8.5)
SMALL   = ParagraphStyle("Small", parent=BODY, fontSize=8, textColor=INK_500)
CAPTION = ParagraphStyle("Cap", parent=BODY, fontSize=8, alignment=TA_CENTER,
    textColor=INK_700, leading=10)


# ============================ helpers ======================================
def _chk(value: bool) -> str:
    """Unambiguous tick / blank cell. The dual-square version (filled vs
    empty) was visually too similar in print, so we now use a clearly
    coloured ✓ for true and a faint em-dash for false.
    """
    if value:
        return ("<font color='#0e7490'>"
                "<b>&#10003;</b></font>")          # ✓ heavy check, brand teal
    return "<font color='#cbd5e1'>&mdash;</font>"  # — light grey


def _yn(value: Optional[bool]) -> str:
    yes = bool(value)
    no = not yes
    return f"{_chk(yes)} Yes &nbsp;&nbsp; {_chk(no)} No"


_THUMB_CACHE: dict[tuple, bytes] = {}
_THUMB_CACHE_LIMIT = 256       # ~10-20 MB worst case


def _make_thumb_bytes(path: Path, target_long_px: int) -> Optional[bytes]:
    """Decode + downscale + JPEG-encode a thumbnail once per (path, size).

    The photo grids embed every photo at the same physical size, so the
    same byte-blob can serve every page that uses that photo at that
    width/height. We key the cache by (path, mtime, target_long_px) so
    re-uploading a different image at the same path invalidates the
    entry automatically.
    """
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime_ns, target_long_px)
    hit = _THUMB_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        with PILImage.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((target_long_px, target_long_px), PILImage.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80, optimize=True)
            data = buf.getvalue()
    except Exception:
        return None
    # cheap LRU-ish: drop arbitrary entries when we go over the limit
    if len(_THUMB_CACHE) >= _THUMB_CACHE_LIMIT:
        for k in list(_THUMB_CACHE.keys())[:32]:
            _THUMB_CACHE.pop(k, None)
    _THUMB_CACHE[key] = data
    return data


def _safe_image(path: str | Path, width: float, height: float) -> Optional[RLImage]:
    try:
        p = Path(path)
        # Pick a thumb size that roughly matches the rendered pixel count
        # at A4 PDF resolution (~150 DPI). This keeps file size + embed
        # cost low without visible quality loss in the PDF.
        target_long = max(int(width / mm * 6.0), int(height / mm * 6.0), 320)
        target_long = min(target_long, 1400)
        data = _make_thumb_bytes(p, target_long)
        if data is None:
            return None
        return RLImage(io.BytesIO(data), width=width, height=height)
    except Exception:
        return None


def _kv_table(rows: list[tuple[str, str]], col_widths=(48 * mm, 110 * mm)) -> Table:
    data = []
    for k, v in rows:
        data.append([Paragraph(k, LBL),
                     Paragraph(str(v) if v not in (None, "") else "—", BODY)])
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, GREY),
    ]))
    return t


def _section_header(text_: str) -> Table:
    """Section header rendered as a full-width band so it always spans the
    text area exactly (Paragraph backColor doesn't stretch to margins)."""
    p = Paragraph(f"<b>{text_}</b>", ParagraphStyle(
        "SH", parent=BODY, fontName="Helvetica-Bold",
        fontSize=11.5, leading=15, textColor=HEADER_FG))
    t = Table([[p]], colWidths=(182 * mm,))
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), HEADER_BG),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEABOVE",     (0, 0), (-1, 0),  0.3, INK_500),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.3, INK_500),
    ]))
    return t


def _two_cols(left, right, col_widths=(95 * mm, 85 * mm)):
    return Table([[left, right]], colWidths=col_widths,
                 style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))


def _photo_grid(images: list[dict], thumb_w: float, thumb_h: float,
                cols: int = 3, captions: Optional[list[str]] = None) -> Table | Paragraph:
    if not images:
        return Paragraph("<i>— no photographs available —</i>", SMALL)
    rows: list[list] = []
    for i in range(0, len(images), cols):
        row_imgs, row_caps = [], []
        for j in range(cols):
            if i + j < len(images):
                im = images[i + j]
                rl = _safe_image(im["path"], thumb_w, thumb_h)
                row_imgs.append(rl or Paragraph("[missing image]", SMALL))
                cap = (captions[i + j] if captions and (i + j) < len(captions)
                       else (im.get("species_top") or "").replace("_", " ").title()
                            or "—")
                row_caps.append(Paragraph(cap, CAPTION))
            else:
                row_imgs.append("")
                row_caps.append("")
        rows.append(row_imgs)
        rows.append(row_caps)
    t = Table(rows, colWidths=[thumb_w + 2 * mm] * cols, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


SEVERITY_LBL = {"A": "A · Light", "B": "B · Moderate", "C": "C · Heavy", "D": "D · Clean"}


# ============================ page chrome ==================================
def _draw_logo(canvas, path: Path | str, x: float, y: float, max_w: float, max_h: float):
    """Draw a logo while preserving aspect ratio inside a max bounding box."""
    try:
        if not path or not Path(path).exists():
            return
        with PILImage.open(path) as im:
            w, h = im.size
        ratio = min(max_w / w, max_h / h)
        dw, dh = w * ratio, h * ratio
        canvas.drawImage(str(path), x, y + (max_h - dh) / 2,
                         width=dw, height=dh, mask="auto",
                         preserveAspectRatio=True)
    except Exception:
        pass


def _make_on_page(settings: dict, vessel_name: str, job_no: str, client_company: str,
                  job_scope: str):
    """Per-page header/footer renderer.

    The CLIENT (vessel owner) is the priority brand and lives in big text on
    the top-right — matching how the template `marine_service_report (2).pdf`
    looks (e.g. "WEST SQUADRON MARINE SERVICES PTE LTD" / "UNDER HULL CLEANING …").
    The diving company (our customer) sits top-left with their logo.
    A thin bar below the banner echoes Vessel Name + Job No. on every page,
    just like the template.
    """
    diving_logo = settings.get("company_logo_path") or ""
    company_name = settings.get("company_name") or "Diving Company"
    report_footer = settings.get("report_footer") or "Powered by NautiCAI"
    report_prefix = settings.get("report_prefix") or "NAUTICAI-REP"
    title_line = (job_scope or "UNDER HULL CLEANING & PROPELLER POLISHING REPORT").upper()
    client = (client_company or "").strip().upper()

    def on_page(canvas, doc):
        canvas.saveState()
        W, H = A4
        BANNER_H = 22 * mm
        SUBBAR_H = 6 * mm   # vessel-name / job-no strip

        # ---- Main banner ----
        canvas.setFillColor(INK_900)
        canvas.rect(0, H - BANNER_H, W, BANNER_H, fill=1, stroke=0)

        # Diving company logo + name (top-left)
        if diving_logo and Path(diving_logo).exists():
            _draw_logo(canvas, diving_logo, 10 * mm, H - BANNER_H + 3.5 * mm,
                       max_w=15 * mm, max_h=15 * mm)
            x_text = 28 * mm
        else:
            x_text = 12 * mm
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(x_text, H - 10 * mm, company_name[:36])
        canvas.setFillColor(BRAND_L)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(x_text, H - 14 * mm, "Prepared by · " + (settings.get("company_tagline") or "")[:50])
        # tiny "Powered by NautiCAI" caption below
        canvas.setFillColor(colors.HexColor("#7dd3fc"))
        canvas.setFont("Helvetica", 6)
        canvas.drawString(x_text, H - 18 * mm, "AI by NautiCAI")

        # CLIENT company name (top-right) — PRIORITY brand
        canvas.setFillColor(colors.white)
        if client:
            canvas.setFont("Helvetica-Bold", 12)
            canvas.drawRightString(W - 10 * mm, H - 10 * mm, client[:55])
        else:
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawRightString(W - 10 * mm, H - 10 * mm, "MARINE SERVICE REPORT")
        canvas.setFillColor(BRAND_L)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawRightString(W - 10 * mm, H - 14 * mm, title_line[:70])

        # ---- Sub-bar: Vessel + Job ----
        canvas.setFillColor(GREY_100)
        canvas.rect(0, H - BANNER_H - SUBBAR_H, W, SUBBAR_H, fill=1, stroke=0)
        canvas.setFillColor(INK_900)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(12 * mm, H - BANNER_H - SUBBAR_H + 1.8 * mm,
                          f"Vessel Name:  ")
        canvas.setFillColor(BRAND)
        canvas.drawString(40 * mm, H - BANNER_H - SUBBAR_H + 1.8 * mm,
                          (vessel_name or "—")[:40])
        canvas.setFillColor(INK_900)
        canvas.drawString(W - 80 * mm, H - BANNER_H - SUBBAR_H + 1.8 * mm,
                          "Job No.:  ")
        canvas.setFillColor(BRAND)
        canvas.drawString(W - 62 * mm, H - BANNER_H - SUBBAR_H + 1.8 * mm,
                          (job_no or "—")[:30])
        # thin separator line
        canvas.setStrokeColor(INK_500)
        canvas.setLineWidth(0.3)
        canvas.line(10 * mm, H - BANNER_H - SUBBAR_H - 0.5 * mm,
                    W - 10 * mm, H - BANNER_H - SUBBAR_H - 0.5 * mm)

        # ---- Footer (2 lines so long strings never collide) ----
        canvas.setFillColor(INK_700)
        canvas.rect(0, 0, W, 13 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 7.5)
        # Top line: report id (left) + page no. (right)
        report_id_line = f"{report_prefix}-{(job_no or '001')[:8]}  ·  Rev 01.{datetime.utcnow().year}"
        canvas.drawString(12 * mm, 7.5 * mm, report_id_line)
        canvas.drawRightString(W - 12 * mm, 7.5 * mm,
                                f"Page {doc.page}")
        # Bottom line: company → client (centred) + powered-by (right)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(BRAND_L)
        client_part = client[:42] if client else "Marine Inspection Client"
        canvas.drawString(12 * mm, 3 * mm,
                          f"Prepared by  {company_name[:36]}   →   for  {client_part}")
        canvas.drawRightString(W - 12 * mm, 3 * mm, report_footer[:32])
        canvas.restoreState()

    return on_page


# ============================ per-region helpers ===========================
def _fouling_pct_pair(species_counts: Dict[str, int], n: int, key: str) -> str:
    val = round(100.0 * species_counts.get(key, 0) / max(n, 1))
    return f"{val}%"


def _fouling_condition_table(meta: Dict[str, Any]) -> Table:
    species_counts = dict(meta.get("species_counts", {}))
    n = int(meta.get("count", 0) or 0)
    avg = float(meta.get("avg_fouling", 0.0) or 0.0)
    rows = [
        [Paragraph("<b>Fouling Condition (AI assessed)</b>", LBL),
         Paragraph(
            f"Algae <b>{_fouling_pct_pair(species_counts, n, 'algae')}</b> &nbsp;·&nbsp; "
            f"Macroalgae <b>{_fouling_pct_pair(species_counts, n, 'macroalgae')}</b> &nbsp;·&nbsp; "
            f"Barnacles <b>{_fouling_pct_pair(species_counts, n, 'barnacles')}</b> &nbsp;·&nbsp; "
            f"Mussels <b>{_fouling_pct_pair(species_counts, n, 'mussels')}</b> &nbsp;·&nbsp; "
            f"Clean Paint <b>{_fouling_pct_pair(species_counts, n, 'clean_paint')}</b>", BODY)],
        [Paragraph("<b>Average Coverage</b>", LBL),
         Paragraph(f"<b>{avg:.0f}%</b> across {n} photo(s)", BODY)],
        [Paragraph("<b>Photos analysed</b>", LBL),
         Paragraph(f"{meta.get('count', 0)}", BODY)],
    ]
    t = Table(rows, colWidths=(48 * mm, 130 * mm))
    t.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND",   (0, 0), (0, -1), GREY_100),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LINEBELOW",    (0, 0), (-1, -1), 0.25, GREY),
        ("BOX",          (0, 0), (-1, -1), 0.25, GREY),
    ]))
    return t


def _manual_findings_table(findings: Dict[str, Any]) -> Table:
    overall = (findings.get("overall_condition") or "Good")
    good = overall.lower() == "good"
    rows = [
        [Paragraph("<b>Overall Condition</b>", LBL),
         Paragraph(f"{_chk(good)} Good &nbsp;&nbsp; {_chk(not good)} Poor", BODY)],
        [Paragraph("<b>Any Damage Observed?</b>", LBL),
         Paragraph(_yn(findings.get("damage_observed", False)), BODY)],
    ]
    if findings.get("damage_notes"):
        rows.append([Paragraph("<b>Damage Notes</b>", LBL),
                     Paragraph(findings["damage_notes"], BODY)])
    if findings.get("notes"):
        rows.append([Paragraph("<b>Surveyor Notes</b>", LBL),
                     Paragraph(findings["notes"].replace("\n", "<br/>"), BODY)])
    t = Table(rows, colWidths=(48 * mm, 130 * mm))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), GREY_50),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, GREY),
        ("BOX", (0, 0), (-1, -1), 0.25, GREY),
    ]))
    return t


def _region_specific_block(region_id: str, findings: Dict[str, Any]) -> Optional[Table]:
    """Region-specific PDF block (Propeller / Rudder / Bilge keels / etc.)."""
    rows: list[list] = []

    if region_id == "Bilege_keels":
        b = findings.get("bilge_keels") or {}
        rows = [
            [Paragraph("<b>Port — No. of Sections</b>", LBL), Paragraph(str(b.get("port_sections") or "—"), BODY),
             Paragraph("<b>Anodes</b>", LBL),                Paragraph(_yn(b.get("port_anodes")), BODY)],
            [Paragraph("<b>Port Anode Depletion</b>", LBL),  Paragraph(str(b.get("port_depletion") or "—"), BODY),
             Paragraph("", LBL),                              Paragraph("", BODY)],
            [Paragraph("<b>Stbd — No. of Sections</b>", LBL), Paragraph(str(b.get("stbd_sections") or "—"), BODY),
             Paragraph("<b>Anodes</b>", LBL),                Paragraph(_yn(b.get("stbd_anodes")), BODY)],
            [Paragraph("<b>Stbd Anode Depletion</b>", LBL),  Paragraph(str(b.get("stbd_depletion") or "—"), BODY),
             Paragraph("", LBL),                              Paragraph("", BODY)],
        ]
        col_widths = (45 * mm, 45 * mm, 35 * mm, 45 * mm)

    elif region_id == "Sea_chest":
        s = findings.get("sea_chest") or {}
        rows = [
            [Paragraph("<b>Port High — Units</b>", LBL),  Paragraph(str(s.get("port_high_units") or "—"), BODY),
             Paragraph("<b>Stbd High — Units</b>", LBL), Paragraph(str(s.get("stbd_high_units") or "—"), BODY)],
            [Paragraph("<b>Gratings Intact?</b>", LBL),   Paragraph(_yn(s.get("gratings_intact", True)), BODY),
             Paragraph("<b>Abnormalities?</b>", LBL),    Paragraph(_yn(s.get("abnormalities", False)), BODY)],
        ]
        col_widths = (40 * mm, 50 * mm, 40 * mm, 50 * mm)

    elif region_id == "Propeller":
        p = findings.get("propeller") or {}
        bt = (p.get("blade_type") or "Fixed").lower()
        rows = [
            [Paragraph("<b>No. of Propeller(s)</b>", LBL), Paragraph(str(p.get("count") or "—"), BODY),
             Paragraph("<b>Total Blade(s) each</b>", LBL), Paragraph(str(p.get("blade_count") or "—"), BODY)],
            [Paragraph("<b>Propeller Diameter (mm)</b>", LBL), Paragraph(str(p.get("diameter") or "—"), BODY),
             Paragraph("<b>Blade Type</b>", LBL),
             Paragraph(f"{_chk('fixed' in bt)} Fixed &nbsp; {_chk('silicon' in bt)} Silicon &nbsp; "
                       f"{_chk('boss' in bt)} Boss Cap &nbsp; {_chk('kurt' in bt)} Kurt Nozzle", BODY)],
            [Paragraph("<b>Before Polish: Oxidised %</b>", LBL),
             Paragraph(str(p.get("oxidised_pct") or "—") + "%" if p.get("oxidised_pct") else "—", BODY),
             Paragraph("<b>After Polish: Rubert Scale</b>", LBL),
             Paragraph(" &nbsp; ".join(
                 f"{_chk((p.get('rubert_scale') or '').upper() == letter)} {letter}"
                 for letter in "ABCDEF"), BODY)],
            [Paragraph("<b>Pitting</b>", LBL),         Paragraph(_yn(p.get("pitting", False)), BODY),
             Paragraph("<b>Cavitation</b>", LBL),     Paragraph(_yn(p.get("cavitation", False)), BODY)],
            [Paragraph("<b>Cracks</b>", LBL),          Paragraph(_yn(p.get("cracks", False)), BODY),
             Paragraph("<b>Previous Repairs</b>", LBL), Paragraph(_yn(p.get("previous_repairs", False)), BODY)],
            [Paragraph("<b>Cement Covers Intact</b>", LBL), Paragraph(_yn(p.get("cement_covers_intact", True)), BODY),
             Paragraph("<b>Bolts Intact</b>", LBL),         Paragraph(_yn(p.get("bolts_intact", True)), BODY)],
            [Paragraph("<b>Cone Securing Bolt Intact</b>", LBL),
             Paragraph(_yn(p.get("cone_bolt_intact", True)), BODY),
             Paragraph("", LBL),                                Paragraph("", BODY)],
        ]
        col_widths = (45 * mm, 45 * mm, 40 * mm, 50 * mm)

    elif region_id == "Radder":
        rd = findings.get("rudder") or {}
        rows = [
            [Paragraph("<b>No. of Rudder(s)</b>", LBL), Paragraph(str(rd.get("count") or "—"), BODY),
             Paragraph("<b>Rudder Type</b>", LBL),     Paragraph(rd.get("type") or "—", BODY)],
            [Paragraph("<b>Plug(s) Intact</b>", LBL),   Paragraph(_yn(rd.get("plug_intact", True)), BODY),
             Paragraph("<b>Anodes Present</b>", LBL),  Paragraph(_yn(rd.get("anodes", True)), BODY)],
            [Paragraph("<b>Anode Depletion</b>", LBL),  Paragraph(str(rd.get("depletion") or "—"), BODY),
             Paragraph("", LBL),                       Paragraph("", BODY)],
        ]
        col_widths = (40 * mm, 50 * mm, 40 * mm, 50 * mm)

    elif region_id == "Rope":
        g = findings.get("rope_guard") or {}
        fitting = (g.get("fitting") or "Welded").lower()
        rc = (g.get("rope_cutters") or "No rope cutters").lower()
        rows = [
            [Paragraph("<b>Fitting</b>", LBL),
             Paragraph(f"{_chk(fitting == 'welded')} Welded &nbsp;&nbsp; {_chk(fitting == 'bolted')} Bolted", BODY),
             Paragraph("<b>Inspection Window</b>", LBL),
             Paragraph(_yn(g.get("inspection_window", True)), BODY)],
            [Paragraph("<b>Rope Cutters</b>", LBL),
             Paragraph(f"{_chk('intact' in rc)} Intact &nbsp; {_chk('missing' in rc)} Missing &nbsp; "
                       f"{_chk('no' in rc and 'cutter' in rc)} None", BODY),
             Paragraph("<b>Oil Leakage</b>", LBL),
             Paragraph(_yn(g.get("oil_leakage", False)), BODY)],
            [Paragraph("<b>Rope Entanglement</b>", LBL), Paragraph(_yn(g.get("rope_entanglement", False)), BODY),
             Paragraph("<b>Entanglement Removed</b>", LBL),
             Paragraph(_yn(g.get("entanglement_removed", False)), BODY)],
        ]
        col_widths = (45 * mm, 45 * mm, 45 * mm, 45 * mm)
    else:
        return None

    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), GREY_50),
        ("BOX", (0, 0), (-1, -1), 0.25, GREY),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _region_inspection_section(region_id: str, bucket: Dict[str, Any],
                                 findings: Dict[str, Any], narrative: Dict[str, Any]) -> list:
    region_display = bucket["_meta"]["region_display"].upper()
    inspect_done = bool(findings.get("inspection_done", True))
    title = f"{region_display} &nbsp;&nbsp; {_chk(inspect_done)} Inspection"

    flow: list = [_section_header(title)]
    flow.append(_fouling_condition_table(bucket["_meta"]))
    flow.append(Spacer(1, 4))
    flow.append(Paragraph(
        f"<b>Surveyor narrative:</b> <i>{narrative['sentence']}</i>", BODY))
    flow.append(Spacer(1, 6))
    flow.append(_manual_findings_table(findings))

    specific = _region_specific_block(region_id, findings)
    if specific is not None:
        flow.append(Spacer(1, 4))
        flow.append(specific)

    flow.append(Spacer(1, 8))
    return flow


# ============================ summary of works ============================
# Maps internal region ids → the human label used in the template's
# "SUMMARY OF WORKS DONE" page.
_SUMMARY_AREAS = [
    ("Bow",                  ["Bow"]),
    ("Port Vertical Side",   ["Verticle_slide", "VerticleSlide", "PortVerticalSide"]),
    ("Starboard Vertical Side", ["Verticle_slide", "VerticleSlide", "StbdVerticalSide"]),
    ("Flat Bottom",          ["Flat_bottom"]),
    ("Bilge Keels",          ["Bilege_keels"]),
    ("Sea Chest Gratings",   ["Sea_chest"]),
    ("Propeller / Rope Guard / Shaft", ["Propeller", "Rope"]),
    ("Rudder / Skeg",        ["Radder"]),
    ("Stern Frame",          ["Stren"]),
    ("Cathodic Protection",  ["Bilege_keels", "Sea_chest", "Radder"]),
]


def _summary_of_works_table(clusters: Dict[str, Any],
                             region_inspections: Optional[Dict[str, Any]] = None) -> Table:
    """Replicates the 'SUMMARY OF WORKS DONE' table from the template:
    a 3-column matrix of Area | Inspected | Cleaned.

    Inspected = region has any photos OR the surveyor ticked Inspection Done.
    Cleaned   = at least one 'after-cleaning' photo for that region.
    """
    region_inspections = region_inspections or {}

    def _is_inspected(region_ids: list[str]) -> bool:
        for rid in region_ids:
            if rid in clusters and clusters[rid].get("_meta", {}).get("count", 0) > 0:
                return True
            if region_inspections.get(rid, {}).get("inspection_done"):
                return True
        return False

    def _is_cleaned(region_ids: list[str]) -> bool:
        for rid in region_ids:
            bucket = clusters.get(rid) or {}
            if bucket.get("after"):
                return True
        return False

    head = [
        Paragraph("<b>Areas</b>", BODY_B),
        Paragraph("<b>Inspected</b>", BODY_B),
        Paragraph("<b>Cleaned</b>", BODY_B),
    ]
    data = [head]
    for label, region_ids in _SUMMARY_AREAS:
        data.append([
            Paragraph(label, BODY),
            Paragraph(_chk(_is_inspected(region_ids)), BODY),
            Paragraph(_chk(_is_cleaned(region_ids)), BODY),
        ])

    # Propeller sub-items (Polishing / Cleaning) — taken straight from findings
    prop_findings = region_inspections.get("Propeller", {}) or {}
    p_block = prop_findings.get("propeller") or {}
    polished = bool(p_block.get("rubert_scale"))
    cleaned  = bool(p_block.get("oxidised_pct"))
    data.append([
        Paragraph("&nbsp;&nbsp;&nbsp; Propeller Polishing", BODY),
        Paragraph(_chk(polished), BODY),
        Paragraph("", BODY),
    ])
    data.append([
        Paragraph("&nbsp;&nbsp;&nbsp; Propeller Cleaning", BODY),
        Paragraph(_chk(cleaned), BODY),
        Paragraph("", BODY),
    ])

    t = Table(data, colWidths=(110 * mm, 30 * mm, 30 * mm), repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK_700),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("ALIGN",      (1, 0), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX",        (0, 0), (-1, -1), 0.4, INK_500),
        ("INNERGRID",  (0, 0), (-1, -1), 0.25, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_50]),
    ]))
    return t


# ============================ executive summary ============================
# Standard 12 locations the marine-survey template prints — even when only
# a subset of regions has images. Each row points to:
#   - source region key:   which AI cluster supplies the species/coverage
#   - template_id:         which sentence template to use (see narrative.py)
# Two locations (Starboard, RudderPintle, DryDocking) share AI data with
# their sibling region but use a different template so the row text reads
# the way the surveyor's manual report does.
_SUMMARY_LOCATIONS = [
    # (display label,        source region,    template_id)
    ("Bow",                   "Bow",            "Bow"),
    ("Port Side",             "Verticle_Slide", "PortSide"),
    ("Starboard Side",        "Verticle_Slide", "Starboard"),
    ("Flat Bottom",           "Flat_bottom",    "Flat_bottom"),
    ("Dry-docking Marks",     "Flat_bottom",    "DryDocking"),
    ("Bilge Keels",           "Bilege_keels",   "Bilege_keels"),
    ("Stern",                 "stren",          "stren"),
    ("Sea Chest Gratings",    "Sea_chest",      "Sea_chest"),
    ("Rudder/S",              "Radder",         "Radder"),
    ("Rudder Pintle Frame",   "Radder",         "RudderPintle"),
    ("Rope Guard",            "Rope",           "Rope"),
    ("Propeller/S",           "Propeller",      "Propeller"),
]

# Species legend numbering matching the source PDF
_SPECIES_LEGEND = [
    ("0", "Clean",      colors.HexColor("#e5e7eb")),
    ("1", "Barnacles",  colors.HexColor("#fde047")),  # highlighted in source
    ("2", "Algae",      colors.HexColor("#86efac")),
    ("3", "Slime",      colors.HexColor("#fde047")),  # highlighted in source
    ("4", "Tubeworm",   colors.HexColor("#e5e7eb")),
    ("5", "Mussels",    colors.HexColor("#e5e7eb")),
    ("6", "Grass",      colors.HexColor("#e5e7eb")),
    ("7", "Calcareous/Other", colors.HexColor("#e5e7eb")),
]


def _species_legend_table() -> Table:
    """The strip above the exec summary explaining the fouling-class codes."""
    row = []
    for num, label, _bg in _SPECIES_LEGEND:
        row.append(Paragraph(
            f"<b>{num}-</b>{label}", SMALL))
    t = Table([row], colWidths=[(170 / len(_SPECIES_LEGEND)) * mm] * len(_SPECIES_LEGEND))
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_L),
        ("TEXTCOLOR",  (0, 0), (-1, -1), INK_900),
        ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("BOX",        (0, 0), (-1, -1), 0.4, INK_500),
        ("INNERGRID",  (0, 0), (-1, -1), 0.25, INK_500),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    # highlight the species we actually detect frequently (yellow tint)
    for i, (_, _, bg) in enumerate(_SPECIES_LEGEND):
        if bg != colors.HexColor("#e5e7eb"):
            style.append(("BACKGROUND", (i, 0), (i, 0), bg))
    t.setStyle(TableStyle(style))
    return t


def _executive_summary_table(clusters: Dict[str, Any]) -> Table:
    """Renders the fixed 12-row 'Fouling Conditions Executive Summary' table
    used in every marine service report, with Yes/No cleaning columns and a
    Remarks column — exactly matching the template the user provided."""
    # Compact, no-wrap header style — keeps "% Area", "Severity", "Yes",
    # "No" on a single line so the header band stays one row high.
    HEAD_STYLE = ParagraphStyle(
        "TblHead", parent=BODY_B, fontSize=8.5, leading=10,
        textColor=colors.white, alignment=TA_CENTER,
    )
    head = [
        Paragraph("Location",            HEAD_STYLE),
        Paragraph("Fouling Conditions Executive", HEAD_STYLE),
        Paragraph("% Area",              HEAD_STYLE),
        Paragraph("Severity",            HEAD_STYLE),
        Paragraph("Yes",                 HEAD_STYLE),
        Paragraph("No",                  HEAD_STYLE),
        Paragraph("Remarks",             HEAD_STYLE),
    ]
    rows = [head]
    for display_label, src_region, template_id in _SUMMARY_LOCATIONS:
        bucket = clusters.get(src_region)
        if not bucket:
            # No images for this region — print a clean placeholder row
            rows.append([
                Paragraph(f"<b>{display_label}</b>", BODY),
                Paragraph("<i>Not inspected / no images.</i>", SMALL),
                Paragraph("—", BODY),
                Paragraph("—", BODY),
                Paragraph("", BODY),
                Paragraph("", BODY),
                Paragraph("", SMALL),
            ])
            continue

        meta = bucket["_meta"]
        narr = narrative_svc.narrative_for_location(template_id, meta)

        # Remarks column — only used when something noteworthy beyond the
        # main sentence stands out (e.g. a secondary species worth listing).
        # We keep this minimal so the row reads cleanly.
        remarks = ""
        if narr["secondary_species"]:
            sec_label = narrative_svc.SPECIES_LABEL_SECONDARY.get(
                narr["secondary_species"], narr["secondary_species"])
            remarks = f"with {sec_label}"

        cleaning = bool(narr["cleaning"])
        rows.append([
            Paragraph(f"<b>{display_label}</b>", BODY),
            Paragraph(narr["sentence"], BODY),
            Paragraph(f"{narr['pct']:.0f}", BODY),
            Paragraph(narr["severity"], BODY),       # A / B / C / D
            Paragraph("X" if cleaning else "", BODY),
            Paragraph("" if cleaning else "X", BODY),
            Paragraph(remarks, SMALL),
        ])

    # Column-width audit: 28+66+14+16+10+10+22 = 166 mm (≤ usable ~182mm)
    t = Table(rows, colWidths=(28 * mm, 66 * mm, 14 * mm, 16 * mm,
                                 10 * mm, 10 * mm, 22 * mm),
              repeatRows=1)
    # Cleaning Yes/No columns are visually grouped via a "Cleaning" caption
    # in the header band — applied via a SPAN-style overlay row above.
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FG),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",      (2, 1), (5, -1), "CENTER"),   # numeric / tick cells centred
        ("ALIGN",      (0, 0), (-1, 0), "CENTER"),   # header row centred
        ("LEFTPADDING",(0, 0), (-1, -1), 4),
        ("RIGHTPADDING",(0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX",        (0, 0), (-1, -1), 0.4, INK_500),
        ("INNERGRID",  (0, 0), (-1, -1), 0.25, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_50]),
    ]))
    return t


# ============================ MAIN BUILD ===================================
def build_pdf(
    out_path: Path, *,
    vessel: dict,
    clusters: dict,
    region_inspections: Optional[Dict[str, Any]] = None,
    vessel_image_path: Optional[str] = None,
    settings: Optional[dict] = None,
    report_id: str,
    created_at: Optional[datetime] = None,
) -> Path:
    out_path = Path(out_path)
    created_at = created_at or datetime.utcnow()
    region_inspections = region_inspections or {}
    settings = settings or {}

    company_name = settings.get("company_name") or "Diving Company"
    vname = vessel.get("vesselName", "") or "—"
    jno   = vessel.get("jobNo", "") or "—"

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=34 * mm, bottomMargin=14 * mm,    # extra top room for the new subbar
        title=f"{company_name} · Marine Service Report · {vname}",
        author=company_name,
    )

    client_info = vessel.get("client") or {}
    client_company = (client_info.get("company") or "").strip()
    job_scope = vessel.get("jobScope") or ""
    on_page = _make_on_page(settings, vname, jno, client_company, job_scope)

    story: list = []

    # ============================================================ Page 1 ====
    story += [
        Paragraph(f"{(job_scope or 'Marine Service Report').title()}", H_TITLE),
        Paragraph(
            f"Report ID <b>{report_id}</b> &nbsp;·&nbsp; "
            f"Created {created_at:%d %b %Y, %H:%M UTC} &nbsp;·&nbsp; "
            f"Prepared by <b>{company_name}</b>"
            + (f" &nbsp;·&nbsp; for <b>{client_company}</b>" if client_company else ""),
            H_SUB,
        ),
    ]

    # ----- Client / Vessel-owner block (PRIORITY brand on the report) ------
    if any([client_company, client_info.get("address"), client_info.get("contact_person"),
            client_info.get("contact_email"), client_info.get("contact_phone")]):
        story.append(_section_header("CLIENT · VESSEL OWNER"))
        cl_left = _kv_table([
            ("Company",          client_company),
            ("Address",          client_info.get("address", "")),
            ("Contact Person",   client_info.get("contact_person", "")),
        ])
        cl_right = _kv_table([
            ("Email",            client_info.get("contact_email", "")),
            ("Phone",            client_info.get("contact_phone", "")),
            ("Vessel",           vname),
        ])
        story.append(_two_cols(cl_left, cl_right))

    # ----- Prepared-By company profile ----------------------------------
    class_approvals = settings.get("class_approvals") or []
    if any([
        settings.get("address"), settings.get("company_address"),
        settings.get("company_phone"), settings.get("company_email"),
        settings.get("company_website"), settings.get("country"),
        settings.get("registration_number"), settings.get("tax_number"),
        class_approvals, settings.get("diving_certifications"),
        settings.get("insurance"), settings.get("established_year"),
    ]):
        story.append(_section_header("PREPARED BY"))
        # IMPORTANT: each sub-table width must fit inside its 95mm half of
        # `_two_cols`. 35 + 55 = 90mm — leaves room for cell padding and
        # prevents long values (company name, email) from spilling into
        # the right column's label area.
        kv_widths = (34 * mm, 56 * mm)
        pb_left = _kv_table([
            ("Company",        settings.get("company_name", "")),
            ("Address",        settings.get("company_address", "")),
            ("Country",        settings.get("country", "")),
            ("Phone",          settings.get("company_phone", "")),
            ("Email",          settings.get("company_email", "")),
            ("Website",        settings.get("company_website", "")),
        ], col_widths=kv_widths)
        pb_right = _kv_table([
            ("Established",        settings.get("established_year", "")),
            ("Registration No.",   settings.get("registration_number", "")),
            ("Tax / VAT No.",      settings.get("tax_number", "")),
            ("Class Approvals",    ", ".join(class_approvals) if class_approvals else ""),
            ("Diving Standards",   settings.get("diving_certifications", "")),
            ("Insurance",          settings.get("insurance", "")),
        ], col_widths=kv_widths)
        story.append(_two_cols(pb_left, pb_right))

    story.append(_section_header("GENERAL INFORMATION"))
    g_left = _kv_table([
        ("Date of Dive",  vessel.get("diveDate", "")),
        ("Job No.",       vessel.get("jobNo", "")),
        ("Vessel Name",   vessel.get("vesselName", "")),
        ("Vessel Type",   vessel.get("vesselType", "")),
        ("Vessel Class",  vessel.get("vesselClass", "")),
    ], col_widths=(34 * mm, 56 * mm))
    g_right = _kv_table([
        ("Job Scope",     vessel.get("jobScope", "")),
        ("Location",      vessel.get("location", "")),
        ("LOA (m)",       vessel.get("loa", "")),
        ("Vessel Draft",  vessel.get("draft", "")),
        ("Captain (Vessel)", vessel.get("captain", "")),
    ], col_widths=(34 * mm, 56 * mm))
    story.append(_two_cols(g_left, g_right))

    # ---------- CLIENT REPRESENTATIVES (Captain etc.) ---------------
    reps = vessel.get("client_reps") or []
    if any((r or {}).get("name") for r in reps):
        story.append(_section_header("CLIENT REPRESENTATIVES"))
        rep_rows = []
        for r in reps:
            role = (r.get("role") or "Captain").strip() or "Captain"
            name = (r.get("name") or "").strip()
            if name:
                rep_rows.append((role, name))
        if rep_rows:
            story.append(_kv_table(rep_rows, col_widths=(48 * mm, 130 * mm)))

    # ---------- One or more DIVING TEAM blocks ----------------------
    crews = vessel.get("crews") or []
    # Back-compat: if no explicit crews but the legacy single-team fields are
    # filled in, synthesise one crew from them so the PDF still renders.
    if not crews and (vessel.get("diveSupervisor") or vessel.get("divers")
                       or vessel.get("boatCaptain")):
        legacy_days_dict = (vessel.get("extra") or {}).get("time_duration") or {}
        legacy_days = [legacy_days_dict[k] for k in sorted(legacy_days_dict.keys())]
        crews = [{
            "label":        "Diving Team",
            "supervisor":   vessel.get("diveSupervisor", ""),
            "divers":       vessel.get("divers", ""),
            "boat_captain": vessel.get("boatCaptain", ""),
            "sea": {
                "weather":    vessel.get("weather", ""),
                "sea":        vessel.get("sea", ""),
                "visibility": vessel.get("visibility", ""),
                "tide":       vessel.get("tide", ""),
            },
            "days":    legacy_days,
            "remarks": vessel.get("notes", ""),
        }]

    for idx, c in enumerate(crews, 1):
        label = (c.get("label") or f"Diving Team - {idx}").upper()
        story.append(_section_header(label))
        # Team line-up
        story.append(_kv_table([
            ("Dive Supervisor",   c.get("supervisor", "")),
            ("Divers and Tenders", c.get("divers",     "")),
            ("Boat Captain",      c.get("boat_captain","")),
        ], col_widths=(48 * mm, 130 * mm)))

        # Sea conditions for this crew
        sea = c.get("sea") or {}
        story.append(Spacer(1, 2))
        story.append(Paragraph("<b>SEA CONDITIONS</b>", H2))
        s_left = _kv_table([
            ("Weather", sea.get("weather", "")),
            ("Sea",     sea.get("sea",     "")),
        ], col_widths=(38 * mm, 52 * mm))
        s_right = _kv_table([
            ("Visibility (m)", sea.get("visibility", "")),
            ("Tide (kn)",      sea.get("tide",       "")),
        ], col_widths=(38 * mm, 52 * mm))
        story.append(_two_cols(s_left, s_right))

        # Days for this crew
        days = c.get("days") or []
        for d_idx, d in enumerate(days, 1):
            day_title = f"TIME AND DURATION OF JOB — Day {d_idx}"
            if d.get("date"):
                day_title += f" &nbsp;·&nbsp; {d['date']}"
            story.append(Spacer(1, 2))
            story.append(Paragraph(f"<b>{day_title}</b>", H2))
            story.append(_kv_table([
                ("Time Left Base",        d.get("time_left_base", "")),
                ("Time Arrived Job Site", d.get("time_arrived_jobsite", "")),
                ("Dive Ops Started",      d.get("dive_ops_started", "")),
                ("Dive Ops Completed",    d.get("dive_ops_completed", "")),
                ("Time Left Job Site",    d.get("time_left_jobsite", "")),
                ("Time Arrived Base",     d.get("time_arrived_base", "")),
                ("Standby Hours (From)",  d.get("standby_from", "")),
                ("Standby Hours (To)",    d.get("standby_to", "")),
            ], col_widths=(55 * mm, 110 * mm)))
            if d.get("remarks"):
                story.append(Paragraph(
                    f"<b>Remarks:</b> {d['remarks']}", BODY))

        if c.get("remarks"):
            story.append(Spacer(1, 2))
            story.append(Paragraph(
                f"<b>Team Remarks:</b> {c['remarks']}", BODY))

        # break to a new page between crews so each crew gets its own section
        if idx < len(crews):
            story.append(PageBreak())

    # ============================================================ Per-region pages ====
    story.append(PageBreak())
    story.append(_section_header("INSPECTION FINDINGS — PER HULL REGION"))

    if clusters:
        for region_id, bucket in clusters.items():
            findings  = region_inspections.get(region_id, {}) if region_inspections else {}
            narr      = narrative_svc.narrative_for_region(region_id, bucket["_meta"])
            story.extend(_region_inspection_section(region_id, bucket, findings, narr))
    else:
        story.append(Paragraph(
            "<i>No images have been uploaded and analysed for this report yet.</i>", BODY))

    # ============================================================ Summary of Works Done ====
    story.append(PageBreak())
    story.append(_section_header("SUMMARY OF WORKS DONE"))
    story.append(_summary_of_works_table(clusters, region_inspections))
    story.append(Spacer(1, 6))

    # Surveyor sign-off (just under the summary, matching the template)
    story.append(Paragraph(
        "We hereby confirm that the above works have been completed with safety.",
        BODY,
    ))
    story.append(Spacer(1, 14))
    sup_name = vessel.get("diveSupervisor") or "_______________________"
    sup_date = vessel.get("diveDate") or "________________"
    sup_table = Table([
        [Paragraph("<b>Dive Supervisor:</b>", LBL),
         Paragraph(sup_name, BODY),
         Paragraph("<b>Date:</b>", LBL),
         Paragraph(sup_date, BODY)],
    ], colWidths=(34 * mm, 70 * mm, 18 * mm, 50 * mm))
    sup_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (1, 0), (1, 0), 0.6, INK_500),
        ("LINEBELOW", (3, 0), (3, 0), 0.6, INK_500),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(sup_table)

    # ============================================================ Executive Summary ====
    story.append(PageBreak())
    story.append(_section_header("FOULING CONDITIONS EXECUTIVE SUMMARY"))
    # Species-code legend strip (0-Clean, 1-Barnacles, …)
    story.append(_species_legend_table())
    story.append(Spacer(1, 4))
    story.append(_executive_summary_table(clusters))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>Severity:</b> &nbsp;(A) Light &nbsp;·&nbsp; (B) Moderate &nbsp;·&nbsp; "
        "(C) Heavy &nbsp;·&nbsp; (D) Clean", SMALL))
    story.append(Paragraph(
        "<i>Descriptions and thickness ranges are inferred from AI image analysis "
        "(per-region species histogram and visual coverage) — they are estimates, "
        "not direct measurements.</i>", SMALL))

    # ============================================================ Photographic Report ====
    story.append(PageBreak())

    # --- Vessel identification opener (matches the source template):
    #     left = large bordered photo, right = sidebar with PHOTOGRAPHIC
    #     REPORT title, vessel name (red), nature of work, date, job no.
    if vessel_image_path and Path(vessel_image_path).exists():
        vimg = _safe_image(vessel_image_path, width=110 * mm, height=80 * mm)
        if vimg is None:
            # fall back to plain section header if the file is missing
            story.append(_section_header("PHOTOGRAPHIC REPORT"))
        else:
            # Sidebar text styles (cyan title + red vessel name)
            S_TITLE = ParagraphStyle("PRTitle", parent=BODY,
                fontName="Helvetica-Bold", fontSize=18, leading=22,
                textColor=BRAND_D, alignment=TA_CENTER, spaceAfter=6)
            S_LBL = ParagraphStyle("PRLbl", parent=BODY,
                fontName="Helvetica-Bold", fontSize=11, leading=14,
                textColor=BRAND_D, alignment=TA_CENTER, spaceBefore=8)
            S_VESSEL = ParagraphStyle("PRVes", parent=BODY,
                fontName="Helvetica-Bold", fontSize=14, leading=18,
                textColor=colors.HexColor("#dc2626"),
                alignment=TA_CENTER, spaceAfter=4)
            S_VAL = ParagraphStyle("PRVal", parent=BODY,
                fontSize=10, leading=13,
                textColor=INK_700, alignment=TA_CENTER, spaceAfter=2)

            # Wrap the photo in a thin blue frame so it visually matches
            # the source template's bordered look.
            bordered_img = Table([[vimg]], colWidths=(112 * mm,))
            bordered_img.setStyle(TableStyle([
                ("LEFTPADDING",   (0, 0), (-1, -1), 2),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 2),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("BOX",           (0, 0), (-1, -1), 3, BRAND),
                ("INNERGRID",     (0, 0), (-1, -1), 0, colors.white),
                ("BACKGROUND",    (0, 0), (-1, -1), colors.white),
            ]))

            sidebar = [
                Paragraph("PHOTOGRAPHIC REPORT", S_TITLE),
                Paragraph("Vessel Name", S_LBL),
                Paragraph(vname.upper() or "—", S_VESSEL),
                Paragraph("Nature of Work", S_LBL),
                Paragraph(job_scope.title() if job_scope else "—", S_VAL),
                Paragraph("Date", S_LBL),
                Paragraph(vessel.get("diveDate") or "—", S_VAL),
                Paragraph("Job Order No.", S_LBL),
                Paragraph(jno or "—", S_VAL),
            ]

            opener = Table([[bordered_img, sidebar]],
                            colWidths=(115 * mm, 65 * mm))
            opener.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING",(0, 0), (-1, -1), 2),
            ]))
            story.append(opener)
            story.append(Spacer(1, 10))
    else:
        story.append(_section_header("PHOTOGRAPHIC REPORT"))

    # --- Per-region Before / After grids ---
    for region_id, bucket in clusters.items():
        meta = bucket["_meta"]
        region_disp = meta["region_display"].upper()
        before_imgs = bucket.get("before", [])
        after_imgs  = bucket.get("after",  [])

        story.append(Paragraph(region_disp, H1))
        # Side-view vessel diagram with red circle on this region
        diagram = diagram_svc.diagram_for_region(
            region_id, display=f"{meta['region_display']} section",
            width_mm=170)
        if diagram is not None:
            story.append(diagram)
            story.append(Spacer(1, 4))
        story.append(Paragraph(f"&#9744; Before Cleaning &nbsp;·&nbsp; {len(before_imgs)} photo(s)", H2))
        story.append(_photo_grid(before_imgs, thumb_w=52 * mm, thumb_h=38 * mm, cols=3))
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"&#9744; After Cleaning &nbsp;·&nbsp; {len(after_imgs)} photo(s)", H2))
        story.append(_photo_grid(after_imgs, thumb_w=52 * mm, thumb_h=38 * mm, cols=3))
        story.append(HRFlowable(width="100%", thickness=0.5, color=GREY,
                                spaceBefore=4, spaceAfter=4))

    # ============================================================ Notes ====
    if vessel.get("notes"):
        story.append(_section_header("REMARKS"))
        story.append(Paragraph(vessel["notes"].replace("\n", "<br/>"), BODY))

    # ============================================================ Sign-off ====
    story.append(Spacer(1, 8))
    story.append(_section_header("SIGN-OFF"))
    sig = Table(
        [
            [Paragraph("<b>Dive Supervisor</b>", LBL),
             Paragraph("<b>Captain (Vessel)</b>", LBL),
             Paragraph("<b>Client Representative</b>", LBL)],
            [Paragraph(vessel.get("diveSupervisor", "_______________________"), BODY),
             Paragraph(vessel.get("captain", "_______________________"), BODY),
             Paragraph("_______________________", BODY)],
            [Paragraph("Sign / Date", SMALL),
             Paragraph("Sign / Date", SMALL),
             Paragraph("Sign / Date", SMALL)],
        ],
        colWidths=(60 * mm, 60 * mm, 60 * mm),
    )
    sig.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, 1), 0.5, INK_500),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
    ]))
    story.append(sig)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out_path
