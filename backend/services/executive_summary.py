"""Dynamic Fouling Conditions Executive Summary — driven by AI image analysis.

Layout matches the marine survey PDF template:
  • Vessel name / job no. line
  • Colour-coded species legend (0–9, all trained fouling classes)
  • 12-row table with AI sentences, % area, severity, cleaning Yes/No, remarks
  • Species names and remarks tinted to match the legend
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import narrative as narrative_svc

# (display label, source region cluster id, narrative template id)
SUMMARY_LOCATIONS: List[Tuple[str, str, str]] = [
    ("Bow", "Bow", "Bow"),
    ("Port Side", "Verticle_Slide", "PortSide"),
    ("Starboard Side", "Verticle_Slide", "Starboard"),
    ("Flat Bottom", "Flat_bottom", "Flat_bottom"),
    ("Dry-docking Marks", "Flat_bottom", "DryDocking"),
    ("Bilge Keels", "Bilege_keels", "Bilege_keels"),
    ("Stern", "stren", "stren"),
    ("Sea Chest Gratings", "Sea_chest", "Sea_chest"),
    ("Rudder/S", "Radder", "Radder"),
    ("Rudder Pintle Frame", "Radder", "RudderPintle"),
    ("Rope Guard", "Rope", "Rope"),
    ("Propeller/S", "Propeller", "Propeller"),
]

# Legend strip — one code per trained fouling class (11-class species model).
SPECIES_LEGEND: List[Tuple[str, str, Tuple[str, ...], Any]] = [
    ("0", "Clean", ("clean_paint",), colors.HexColor("#e5e7eb")),
    ("1", "Slime", ("slime",), colors.HexColor("#fed7aa")),
    ("2", "Algae", ("algae", "macroalgae"), colors.HexColor("#86efac")),
    ("3", "Grass", ("grass",), colors.HexColor("#bbf7d0")),
    ("4", "Tubeworm", ("tubeworms",), colors.HexColor("#ddd6fe")),
    ("5", "Barnacles", ("barnacles",), colors.HexColor("#fde047")),
    ("6", "Mussels", ("mussels",), colors.HexColor("#bfdbfe")),
    ("7", "Goosenecks", ("goosenecks",), colors.HexColor("#fcd34d")),
    ("8", "Calcareous", ("calcareous",), colors.HexColor("#d6d3d1")),
    ("9", "Mixed", ("mixed_fouling",), colors.HexColor("#9ca3af")),
]

SPECIES_TEXT_COLOR: Dict[str, str] = {
    "slime": "#c2410c",
    "algae": "#15803d",
    "macroalgae": "#15803d",
    "grass": "#166534",
    "barnacles": "#a16207",
    "mussels": "#1d4ed8",
    "tubeworms": "#6d28d9",
    "goosenecks": "#92400e",
    "calcareous": "#57534e",
    "mixed_fouling": "#374151",
    "clean_paint": "#4b5563",
}


def _species_in_report(clusters: Dict[str, Any]) -> Set[str]:
    found: Set[str] = set()
    for bucket in clusters.values():
        meta = bucket.get("_meta") or {}
        for sid in (meta.get("species_counts") or {}):
            found.add(sid)
    return found


def build_executive_header(
    vessel_name: str,
    job_no: str,
    *,
    body_style,
) -> Paragraph:
    vname = (vessel_name or "—").strip().upper()
    jno = (job_no or "—").strip()
    return Paragraph(
        f"<b>VESSEL NAME:</b> {vname} &nbsp;&nbsp;&nbsp; <b>Job No.:</b> {jno}",
        body_style,
    )


def build_species_legend_table(
    clusters: Dict[str, Any],
    *,
    small_style,
    default_band_bg,
) -> Table:
    """Colour legend — highlights species the AI actually found in this report."""
    present = _species_in_report(clusters)
    row = []
    for num, label, model_ids, highlight_bg in SPECIES_LEGEND:
        active = any(m in present for m in model_ids) if model_ids else False
        row.append(Paragraph(f"<b>{num}-</b>{label}", small_style))

    t = Table([row], colWidths=[(170 / len(SPECIES_LEGEND)) * mm] * len(SPECIES_LEGEND))
    style: list = [
        ("BACKGROUND", (0, 0), (-1, -1), default_band_bg),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#6b7280")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9ca3af")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, (_, _, model_ids, highlight_bg) in enumerate(SPECIES_LEGEND):
        if model_ids and any(m in present for m in model_ids):
            style.append(("BACKGROUND", (i, 0), (i, 0), highlight_bg))
        elif not model_ids:
            style.append(("BACKGROUND", (i, 0), (i, 0), highlight_bg))
    t.setStyle(TableStyle(style))
    return t


def _colored_label(species_id: str, *, secondary: bool = False) -> str:
    if secondary:
        text = narrative_svc.SPECIES_LABEL_SECONDARY.get(
            species_id, species_id.lower())
    else:
        text = narrative_svc.SPECIES_LABEL.get(species_id, species_id.capitalize())
    color = SPECIES_TEXT_COLOR.get(species_id, "#111827")
    return f'<font color="{color}"><b>{text}</b></font>'


def colorize_species_phrase(primary: str, secondary: Optional[str]) -> str:
    """Coloured 'Barnacles and algae' fragment for the executive sentence."""
    p = _colored_label(primary, secondary=False)
    if not secondary:
        return p
    s = _colored_label(secondary, secondary=True)
    return f"{p} and {s}"


def colorize_executive_sentence(narr: Dict[str, Any]) -> str:
    """Inject legend-matched colours into the fouling sentence."""
    plain = narr["sentence"]
    if narr.get("severity") == "D" or narr.get("primary_species") == "clean_paint":
        return plain
    primary = narr["primary_species"]
    secondary = narr.get("secondary_species")
    plain_phrase = narrative_svc._species_phrase(primary, secondary)
    colored_phrase = colorize_species_phrase(primary, secondary)
    if plain_phrase in plain:
        return plain.replace(plain_phrase, colored_phrase, 1)
    return plain


def build_remarks_html(narr: Dict[str, Any]) -> str:
    """Remarks column — e.g. green 'with algae' like the reference PDF."""
    parts: List[str] = []
    if narr.get("secondary_species"):
        sec = narr["secondary_species"]
        sec_lbl = narrative_svc.SPECIES_LABEL_SECONDARY.get(sec, sec.lower())
        color = SPECIES_TEXT_COLOR.get(sec, "#111827")
        parts.append(f'<font color="{color}">with {sec_lbl}</font>')
    elif narr.get("primary_species") and narr.get("severity") != "D":
        prim = narr["primary_species"]
        if prim != "clean_paint":
            lbl = narrative_svc.SPECIES_LABEL.get(prim, prim)
            color = SPECIES_TEXT_COLOR.get(prim, "#111827")
            parts.append(f'<font color="{color}">{lbl}</font>')
    if narr.get("image_count"):
        parts.append(f"{narr['image_count']} photo(s)")
    return "; ".join(parts)


def inspection_summary_paragraph(clusters: Dict[str, Any]) -> str:
    """UW hull inspection opener — built from analysed regions, not reference PDF text."""
    parts: List[str] = []
    for label, rid, tpl in [
        ("bow area", "Bow", "Bow"),
        ("vertical sides", "Verticle_Slide", "PortSide"),
        ("flat bottom", "Flat_bottom", "Flat_bottom"),
        ("bilge keels", "Bilege_keels", "Bilege_keels"),
        ("sea chest gratings", "Sea_chest", "Sea_chest"),
        ("rudder", "Radder", "Radder"),
        ("propeller", "Propeller", "Propeller"),
    ]:
        bucket = clusters.get(rid)
        if not bucket:
            continue
        meta = bucket.get("_meta") or {}
        if not meta.get("count"):
            continue
        narr = narrative_svc.narrative_for_location(tpl, meta)
        if narr["severity"] == "D":
            continue
        sent = narr["sentence"]
        if " is fouled by " in sent:
            parts.append(f"on the {label}, fouling by {sent.split(' is fouled by ', 1)[-1]}")
        elif " appears clean" in sent or " appear clean" in sent:
            parts.append(f"the {label} appears clean")
        else:
            parts.append(sent[0].lower() + sent[1:] if sent else sent)

    if not parts:
        return (
            "Underwater inspection was conducted on the submitted photographs. "
            "No significant fouling was identified in the analysed hull regions. "
            "Overall paint condition appeared satisfactory where images were available."
        )
    return (
        "Based on AI-assisted analysis of the submitted underwater photographs, "
        "marine growth was documented as follows: "
        + "; ".join(parts[:7])
        + ". Overall hull paint condition was assessed from the image set. "
        "Cleaning scope followed the fouling assessment above."
    )


def build_executive_summary_table(
    clusters: Dict[str, Any],
    *,
    body_style,
    body_bold_style,
    small_style,
    head_style,
    header_bg,
    row_alt: Optional[Any] = None,
    col_widths: Optional[tuple] = None,
) -> Table:
    """12-row executive summary — AI sentences with coloured species + remarks."""
    if col_widths is None:
        col_widths = (28 * mm, 66 * mm, 14 * mm, 16 * mm, 10 * mm, 10 * mm, 22 * mm)
    if row_alt is None:
        row_alt = colors.HexColor("#f9fafb")

    head = [
        Paragraph("Location", head_style),
        Paragraph("Fouling Conditions Executive", head_style),
        Paragraph("% Area", head_style),
        Paragraph("Severity", head_style),
        Paragraph("Yes", head_style),
        Paragraph("No", head_style),
        Paragraph("Remarks", head_style),
    ]
    rows = [head]

    for display_label, src_region, template_id in SUMMARY_LOCATIONS:
        bucket = clusters.get(src_region)
        if not bucket:
            rows.append([
                Paragraph(f"<b>{display_label}</b>", body_style),
                Paragraph("<i>Not inspected / no images.</i>", small_style),
                Paragraph("—", body_style),
                Paragraph("—", body_style),
                Paragraph("", body_style),
                Paragraph("", body_style),
                Paragraph("", small_style),
            ])
            continue

        meta = bucket["_meta"]
        narr = narrative_svc.narrative_for_location(template_id, meta)
        cleaning = bool(narr["cleaning"])
        remarks_html = build_remarks_html(narr)

        rows.append([
            Paragraph(f"<b>{display_label}</b>", body_style),
            Paragraph(colorize_executive_sentence(narr), body_style),
            Paragraph(f"{narr['pct']:.0f}", body_style),
            Paragraph(str(narr["severity"]), body_style),
            Paragraph("X" if cleaning else "", body_style),
            Paragraph("" if cleaning else "X", body_style),
            Paragraph(remarks_html, small_style) if remarks_html else Paragraph("", small_style),
        ])

    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 1), (5, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("ALIGN", (6, 0), (6, -1), "LEFT"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#6b7280")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, row_alt]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t
