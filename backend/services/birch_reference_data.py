"""Static survey data extracted from the BW BIRCH reference PDF (Fujairah, June 2024)."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Names replaced by the NautiCAI logo on BW BIRCH / marine survey PDFs.
_PARTNER_RE = re.compile(
    r"azolla|synergy(?:\s+group)?|your\s+decarbonization\s+partner|"
    r"atlantic\s+dive\s+services(?:\s+premium)?",
    re.IGNORECASE,
)

NAUTICAI_LOGO_PATH = Path(__file__).resolve().parent.parent.parent / "image.png"


def strip_partner_text(text: str) -> str:
    """Remove Azolla / partner tagline from any report string."""
    if not text:
        return ""
    out = _PARTNER_RE.sub("", str(text))
    out = re.sub(r"\s*[,·|→]+\s*", " ", out)
    return re.sub(r"\s+", " ", out).strip(" ,·→")


def report_company_name(settings: dict, *, default: str = "NautiCAI") -> str:
    """Metadata label only — header uses the NautiCAI logo, not this text."""
    name = strip_partner_text((settings or {}).get("company_name") or "")
    return name or default

BIRCH_VESSEL_DEFAULTS: Dict[str, Any] = {
    "vesselType": "LPG TANKER",
    "loa": "225m x 36m",
    "draft": "7.5 m",
    "location": "Fujairah, UAE",
    "diveDate": "13/06/2024",
    "weather": "Fair",
    "sea": "Fair",
    "visibility": "Satisfactory",
    "jobScope": "UW Inspection",
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
        "embed_reference_photos": True,
    },
}

# Marine-template "Summary of Works Done" — from reference PDF section C (BW BIRCH, Fujairah).
BIRCH_SUMMARY_WORKS: List[Tuple[str, bool, bool]] = [
    # (area label, inspected, cleaned)
    ("Bow", True, True),
    ("Port Vertical Side", True, True),
    ("Starboard Vertical Side", True, True),
    ("Flat Bottom", True, True),
    ("Bilge Keels", True, True),
    ("Sea Chest Gratings", True, True),
    ("Propeller / Rope Guard / Shaft", True, True),
    ("Rudder / Skeg", True, True),
    ("Stern Frame", True, True),
    ("Cathodic Protection", True, False),
    ("Propeller Polishing", True, False),
    ("Propeller Cleaning", True, True),
]

BIRCH_INSPECTION_SUMMARY = (
    "Upon request for UWI&amp;C, underwater inspection, propeller polishing and hull cleaning were "
    "conducted on 13/06/2024. Based on inspection, the vessel was fouled with marine growth: "
    "bow area slime about 80–90% with heavy fouling and barnacles about 30–40% with moderate fouling; "
    "forward and midship vertical sides with heavy grass about 80–90% and barnacles 20–30%; "
    "aft sides with grass 50–60% and heavy slime; flat bottom with slime 20–60% and barnacles 40–80%; "
    "bilge keels with 100% slime and ~30% barnacles; intake grids and EFP with heavy slime and "
    "70–80% barnacles; rudder with heavy grass and light barnacles; propeller with heavy calcium "
    "deposits and slime. Overall hull paint condition was good. UW hull cleaning (incl. bilge keels, "
    "sea chest grids and rudder) and propeller polishing were performed per the fouling assessment."
)

# Executive-summary rows (marine template locations) — from reference survey.
BIRCH_EXECUTIVE_ROWS: List[Dict[str, Any]] = [
    {
        "location": "Bow",
        "sentence": (
            "The bulbous bow area is fouled by Slime with 3–5mm thickness and barnacles "
            "with 2–5mm thickness."
        ),
        "pct": 85, "severity": "C", "cleaning": True, "remarks": "S/H/90%; B/M/30-40%",
    },
    {
        "location": "Port Side",
        "sentence": (
            "The port vertical side from forward to aft is fouled by Algae (grass) and barnacles "
            "with 5–8mm thickness."
        ),
        "pct": 90, "severity": "C", "cleaning": True, "remarks": "G/H/100%; B/M/20-30%",
    },
    {
        "location": "Starboard Side",
        "sentence": (
            "The starboard vertical side from forward to aft is fouled by Algae (grass) and barnacles "
            "with 5–8mm thickness."
        ),
        "pct": 90, "severity": "C", "cleaning": True, "remarks": "G/H/100%; B/M/20-30%",
    },
    {
        "location": "Flat Bottom",
        "sentence": (
            "The flat bottom is fouled by barnacles and Slime with 2–6mm thickness."
        ),
        "pct": 55, "severity": "B", "cleaning": True, "remarks": "B/M/40-50%; S/L/20-60%",
    },
    {
        "location": "Dry-docking Marks",
        "sentence": (
            "Dry-docking marks on the flat bottom show barnacles and Slime with 2–5mm thickness."
        ),
        "pct": 45, "severity": "B", "cleaning": True, "remarks": "",
    },
    {
        "location": "Bilge Keels",
        "sentence": (
            "Bilge keels at port and starboard are fouled by Slime and barnacles with 5–8mm thickness."
        ),
        "pct": 95, "severity": "C", "cleaning": True, "remarks": "S/H/100%; B/M/30%",
    },
    {
        "location": "Stern",
        "sentence": "The stern area shows moderate grass and heavy slime fouling.",
        "pct": 70, "severity": "B", "cleaning": True, "remarks": "",
    },
    {
        "location": "Sea Chest Gratings",
        "sentence": (
            "Sea chest gratings are fouled by Slime and barnacles with 8–12mm thickness."
        ),
        "pct": 95, "severity": "C", "cleaning": True, "remarks": "S/H/100%; B/M/70-80%",
    },
    {
        "location": "Rudder/S",
        "sentence": (
            "The rudder blade is fouled by Algae (grass) and barnacles with 3–6mm thickness."
        ),
        "pct": 90, "severity": "C", "cleaning": True, "remarks": "G/H/100%; B/L/20%",
    },
    {
        "location": "Rudder Pintle Frame",
        "sentence": "The rudder pintle frame shows similar fouling to the rudder blade.",
        "pct": 75, "severity": "B", "cleaning": True, "remarks": "",
    },
    {
        "location": "Rope Guard",
        "sentence": "The rope guard appears clean with no significant fouling observed.",
        "pct": 5, "severity": "D", "cleaning": False, "remarks": "",
    },
    {
        "location": "Propeller/S",
        "sentence": (
            "Propeller blades are fouled by calcareous deposits and Slime with 8–12mm thickness."
        ),
        "pct": 95, "severity": "C", "cleaning": True, "remarks": "CD/H/100%; S/H/80%",
    },
]

# (AREA, sub-area) -> fouling cells + hull/paint condition
BIRCH_HULL_FOULING: Dict[Tuple[str, str], Dict[str, str]] = {
    ("BOW", "Port"):       {"f1": "S/H/90%", "f2": "B/M/30-40%", "f3": "", "hull": "Good", "paint": "Poor"},
    ("BOW", "Starboard"):  {"f1": "S/H/90%", "f2": "B/M/30-40%", "f3": "", "hull": "Good", "paint": "Poor"},
    ("BOW", "Bottom"):     {"f1": "B/H/70-80%", "f2": "S/L/50-60%", "f3": "", "hull": "Good", "paint": "Poor"},
    ("BOW", "Thruster/s"): {"f1": "NA", "f2": "", "f3": "", "hull": "NA", "paint": "NA"},
    ("FORWARD", "Port"):       {"f1": "G/H/100%", "f2": "B/M/20-30%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("FORWARD", "Starboard"):  {"f1": "G/H/100%", "f2": "B/M/20-30%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("FORWARD", "Bottom"):     {"f1": "B/M/40-50%", "f2": "S/L/20-30%", "f3": "", "hull": "Good", "paint": "Good"},
    ("MIDSHIP", "Port"):       {"f1": "G/H/100%", "f2": "B/M/20-30%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("MIDSHIP", "Starboard"):  {"f1": "G/H/100%", "f2": "B/M/20-30%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("MIDSHIP", "Bottom"):     {"f1": "B/M/30-40%", "f2": "S/L/50-60%", "f3": "", "hull": "Good", "paint": "Good"},
    ("AFT", "Port"):       {"f1": "G/M/50-60%", "f2": "S/H/100%", "f3": "B/M/30-40%", "hull": "Good", "paint": "Fair"},
    ("AFT", "Starboard"):  {"f1": "G/M/50-60%", "f2": "S/H/100%", "f3": "B/M/30-40%", "hull": "Good", "paint": "Fair"},
    ("AFT", "Bottom"):     {"f1": "B/H/60-70%", "f2": "S/L/50-60%", "f3": "", "hull": "Good", "paint": "Good"},
    ("BILGE KEELS", "Port"):     {"f1": "S/H/100%", "f2": "B/M/30%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("BILGE KEELS", "Starboard"): {"f1": "S/H/100%", "f2": "B/M/30%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("INTAKE GRIDS", "Port"):     {"f1": "S/H/100%", "f2": "B/M/70-80%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("INTAKE GRIDS", "Starboard"): {"f1": "S/H/100%", "f2": "B/M/70-80%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("INTAKE GRIDS", "EFP"):      {"f1": "S/H/100%", "f2": "B/M/70-80%", "f3": "", "hull": "Good", "paint": "Fair"},
    ("PROPELLER", "Blade"):     {"f1": "CD/H/100%", "f2": "S/H/80%", "f3": "B/L/5-10%", "hull": "Good", "paint": "NA"},
    ("PROPELLER", "Boss Cone"): {"f1": "CD/H/100%", "f2": "S/H/80%", "f3": "", "hull": "Good", "paint": "NA"},
    ("RUDDER", "—"):           {"f1": "—", "f2": "G/H/100%", "f3": "B/L/20%", "hull": "Good", "paint": "Fair"},
}

BIRCH_ANTIFOULING: List[Dict[str, Any]] = [
    {"location": "BOW", "type": "5", "pct": "", "good": False, "fair": False, "poor": True},
    {"location": "PORT VERTICAL", "type": "", "pct": "", "good": False, "fair": True, "poor": False},
    {"location": "STBD VERTICAL", "type": "", "pct": "", "good": False, "fair": True, "poor": False},
    {"location": "FLAT BOTTOM", "type": "", "pct": "", "good": False, "fair": True, "poor": False},
    {"location": "INTAKE GRIDS", "type": "", "pct": "", "good": False, "fair": False, "poor": True},
    {"location": "RUDDER", "type": "", "pct": "", "good": False, "fair": False, "poor": True},
]

BIRCH_APPENDAGES: Dict[str, Any] = {
    "bilge_keels": {
        "type_split": True,
        "sections": "4",
        "port_indent": False, "port_cracks": False,
        "stbd_indent": False, "stbd_cracks": False,
        "port_anodes": "--", "port_anode_pct": "--",
        "stbd_anodes": "--", "stbd_anode_pct": "--",
    },
    "sea_chest": {
        "securing": "bolted",
        "condition_good": True,
        "nuts_intact": True,
        "total": "5", "port": "5", "stbd": "--", "bottom": "1", "efp": "1",
        "remarks": "",
    },
    "cathodic": {
        "iccp_yes": True, "damage": False, "anodes": "4",
        "remarks": (
            "5 Sea Chest grids on STBD Side. 5 Sea Chest grids on PORT Side. "
            "1 EFP on PORT Side. No items of concern were observed."
        ),
    },
    "stern_frame": {
        "casting_good": True, "rudder_weld_good": True, "hull_weld_good": True,
        "skeg_na": True, "damage": False, "anodes": "--", "anode_pct": "--",
    },
    "rope_guard": {
        "condition_good": True, "securing_welded": True,
        "obs_top": True, "obs_bottom": True,
        "rope_cutters": True, "damage": False,
        "cutters_fitted": "", "cutters_damaged": "",
    },
    "propeller": {
        "diameter": "7000mm", "blades": "4", "conventional": True, "cpp": False,
        "single": True, "twin": False,
        "pressure_pre": ["D", "D", "D", "D", "NA", "NA"],
        "pressure_post": ["A", "A", "A", "A", "NA", "NA"],
        "suction_pre": ["D", "D", "D", "D", "NA", "NA"],
        "suction_post": ["A", "A", "A", "A", "NA", "NA"],
        "blade_good": True, "pitting": False, "cavitation": False,
        "nick": False, "cracks": False, "bend": False, "prev_repair": False,
        "boss_good": True, "remarks": "Overall, the condition of the propeller was in good condition.",
    },
    "rudder": {
        "type_hanging": True, "plate_good": True, "cracks": False,
        "plugs": "1", "plugs_intact": True,
        "horn_damage": False, "stock_damage": False,
        "access_port": True, "access_bolted": True, "access_damage": False,
        "skeg_damage_na": True, "anodes": "--", "anode_pct": "--",
        "remarks": "No item of concern was observed.",
    },
}


def is_birch_report(vessel: dict) -> bool:
    return "BIRCH" in (vessel.get("vesselName") or "").upper()


def merge_birch_vessel(vessel: dict) -> dict:
    v = dict(vessel)
    if not is_birch_report(v):
        return v
    for k, val in BIRCH_VESSEL_DEFAULTS.items():
        if k == "extra":
            ex = dict(v.get("extra") or {})
            ex.update(val or {})
            v["extra"] = ex
        elif not v.get(k):
            v[k] = val
    ex = v.get("extra") or {}
    if not v.get("diveSupervisor"):
        v["diveSupervisor"] = ex.get("supervisor_1", "")
    if not v.get("divers"):
        v["divers"] = ex.get("divers_list", "")
    # Keep notes separate from works_remarks (already shown under Summary of Works).
    if not v.get("crews"):
        v["crews"] = [{
            "label": "Diving Team",
            "supervisor": ex.get("supervisor_1", ""),
            "divers": ex.get("divers_list", ""),
            "boat_captain": v.get("boatCaptain", ""),
            "sea": {
                "weather": v.get("weather", ""),
                "sea": v.get("sea", ""),
                "visibility": v.get("visibility", ""),
                "tide": v.get("tide", ""),
            },
            "days": [{
                "date": v.get("diveDate", ""),
                "time_left_base": ex.get("mob_day1_from", ""),
                "time_arrived_jobsite": ex.get("mob_day1_from", ""),
                "dive_ops_started": ex.get("ops_day1_start", ""),
                "dive_ops_completed": ex.get("ops_day1_stop", ""),
                "time_left_jobsite": ex.get("mob_day1_to", ""),
                "time_arrived_base": ex.get("mob_day1_to", ""),
                "remarks": ex.get("works_remarks", ""),
            }],
            "remarks": ex.get("works_remarks", ""),
        }]
    return v


def azolla_settings(settings: dict) -> dict:
    """Legacy alias — partner branding removed; same as birch_marine_pdf_settings."""
    return birch_marine_pdf_settings(settings)


def birch_marine_pdf_settings(settings: dict) -> dict:
    """BW BIRCH marine PDF: no partner branding, no cover ship photo, no header vessel name."""
    s = dict(settings or {})
    s["exclude_partner_branding"] = True
    s["use_azolla_branding"] = False
    s["hide_header_partner_branding"] = True
    s["hide_header_vessel_name"] = True
    s["hide_cover_vessel_photo"] = True
    s["hide_cover_vessel_name"] = True
    s["hide_cover_prepared_by"] = True
    s["use_nauticai_header_logo"] = True
    s["company_logo_path"] = str(NAUTICAI_LOGO_PATH) if NAUTICAI_LOGO_PATH.exists() else ""
    s["company_name"] = report_company_name(s)
    s["company_tagline"] = strip_partner_text(s.get("company_tagline") or "") or (
        "Marine inspection & cleaning services"
    )
    s["report_footer"] = strip_partner_text(s.get("report_footer") or "") or "Powered by NautiCAI"
    return s
