"""Extract embedded photographs from a legacy survey PDF (e.g. BW BIRCH).

Groups images by section headings found in the document text so section G of
our UW report can mirror the original photo layout.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config

_TITLE_HINTS = (
    "Pre-Cleaning", "Post Cleaning", "Before Cleaning", "After Cleaning",
    "Pre-Polishing", "Post Polishing", "Pre / Post", "Boss Cone",
    "Vertical Sides", "Flat Bottom", "Bilge Keels", "Sea Chest",
    "Propeller ", "Rudder ",
)


def _is_section_title(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 120:
        return False
    if "PHOTOGRAPH" in line.upper():
        return False
    if line.startswith("G)"):
        return False
    return any(h in line for h in _TITLE_HINTS)


def _carry_section(prev: str, line: str) -> str:
    line = line.strip()
    if not line:
        return prev
    if line.startswith("Blade No") or line in ("PORT SIDE", "STBD SIDE"):
        return prev
    if _is_section_title(line):
        return line
    if line.startswith("(Midship") or line.startswith("(Forward"):
        base = prev.split("(")[0].strip() if prev else "Photographs"
        return f"{base} {line}"
    return prev


def _save_xref_pix(doc, xref: int) -> Optional[Any]:
    import fitz  # PyMuPDF

    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        if pix.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.width < 100 or pix.height < 100:
            return None
        if pix.width * pix.height < 15000:
            return None
        return pix
    except Exception:
        return None


def _cache_dir(pdf_path: Path) -> Path:
    key = hashlib.sha256(str(pdf_path.resolve()).encode()).hexdigest()[:16]
    return config.STORAGE_DIR / "pdf_extracts" / key


def extraction_cache_dir(pdf_path: Path | str) -> Path:
    """Folder where ``extract_pdf_photos`` writes ``manifest.json`` and ``*.jpg``."""
    return _cache_dir(Path(pdf_path))


def extract_pdf_photos(
    pdf_path: Path,
    *,
    photo_start_page: int = 9,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Extract images from *pdf_path*; return manifest grouped by section.

    Cached under ``backend/storage/pdf_extracts/<hash>/``.
    """
    import fitz

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"sections": [], "images": [], "source": str(pdf_path)}

    cache = _cache_dir(pdf_path)
    manifest_path = cache / "manifest.json"
    if manifest_path.exists() and not force_refresh:
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    cache.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))

    def _caption_candidates(page) -> List[str]:
        out: List[str] = []
        for ln in page.get_text().splitlines():
            ln = ln.strip().replace("\ufffd", "–")
            if not ln or len(ln) < 3 or len(ln) > 95:
                continue
            if _is_section_title(ln) or ln.startswith("G)") or "PHOTOGRAPH" in ln.upper():
                continue
            if ln.startswith("(") and "to" in ln.lower() and ln.endswith(")"):
                continue
            if re.match(r"^[\d\s./:]+$", ln):
                continue
            out.append(ln)
        return out

    current = "Photographs"
    entries: List[Dict[str, Any]] = []
    idx = 0

    for pno in range(photo_start_page - 1, doc.page_count):
        page = doc[pno]
        for line in page.get_text().splitlines():
            current = _carry_section(current, line)

        captions_q = _caption_candidates(page)
        img_n = 0
        for img in page.get_images(full=True):
            xref = img[0]
            pix = _save_xref_pix(doc, xref)
            if pix is None:
                continue
            idx += 1
            img_n += 1
            rel = f"{idx:03d}.jpg"
            out_file = cache / rel
            pix.save(str(out_file), jpg_quality=88)
            cap = captions_q.pop(0) if captions_q else None
            if not cap:
                cap = f"{current.replace(chr(0xFFFD), '–')} — Image {img_n}"
            entries.append({
                "file": str(out_file),
                "section": current,
                "page": pno + 1,
                "caption": cap,
            })

    doc.close()

    grouped: Dict[str, List[Dict[str, str]]] = {}
    for e in entries:
        grouped.setdefault(e["section"], []).append({
            "path": e["file"],
            "caption": e.get("caption") or e["section"],
        })

    manifest = {
        "source": str(pdf_path.resolve()),
        "sections": [
            {
                "title": title.replace("\ufffd", "–"),
                "photos": photos,
                "paths": [p["path"] for p in photos],
            }
            for title, photos in grouped.items()
        ],
        "images": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    return manifest


def extract_cover_vessel_image(pdf_path: Path, out_path: Optional[Path] = None) -> Optional[Path]:
    """Largest photograph on page 1 (cover vessel shot)."""
    import fitz

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return None
    out_path = Path(out_path or (config.BACKEND_DIR / "assets" / "report" / "birch_cover_vessel.jpg"))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    if doc.page_count < 1:
        doc.close()
        return None
    page = doc[0]
    best_pix = None
    best_area = 0
    for img in page.get_images(full=True):
        try:
            pix = fitz.Pixmap(doc, img[0])
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)
            if pix.n > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            area = pix.width * pix.height
            if area > best_area and pix.width > 400 and pix.height > 300:
                best_area = area
                best_pix = pix
        except Exception:
            continue
    doc.close()
    if best_pix is None:
        return None
    best_pix.save(str(out_path), jpg_quality=92)
    return out_path


def default_birch_source_pdf() -> Optional[Path]:
    """Project-root BW BIRCH reference report, if present."""
    root = config.PROJECT_ROOT
    exact = root / "Final Report - BW BIRCH - UWI, HC & PP in Fujairah, UAE.pdf"
    if exact.exists():
        return exact
    for p in root.glob("Final Report - BW BIRCH*.pdf"):
        return p
    return None


def resolve_source_pdf(vessel: dict, explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    extra = vessel.get("extra") or {}
    if extra.get("source_pdf"):
        p = Path(extra["source_pdf"])
        if p.exists():
            return p
    if extra.get("use_birch_reference") or "BIRCH" in (vessel.get("vesselName") or "").upper():
        return default_birch_source_pdf()
    return None


def resolve_source_pdf_for_photos(
    vessel: dict,
    explicit: Optional[str] = None,
    *,
    clusters: Optional[dict] = None,
) -> Optional[Path]:
    """Source PDF for photographic sections (BW BIRCH reference or explicit path)."""
    p = resolve_source_pdf(vessel, explicit)
    if p:
        return p
    extra = vessel.get("extra") or {}
    if extra.get("embed_reference_photos"):
        return default_birch_source_pdf()
    if "BIRCH" in (vessel.get("vesselName") or "").upper():
        return default_birch_source_pdf()
    if clusters is not None and not clusters:
        return default_birch_source_pdf()
    return None


def _section_base(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", title.replace("\ufffd", "–").strip()).strip() or title


def merge_photo_sections(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for block in manifest.get("sections") or []:
        title = (block.get("title") or "Photographs").replace("\ufffd", "–")
        photos = list(block.get("photos") or [])
        if not photos and block.get("paths"):
            photos = [{"path": p, "caption": title} for p in block["paths"]]
        base = _section_base(title)
        if merged and _section_base(merged[-1]["title"]) == base:
            merged[-1]["photos"].extend(photos)
            if "(" in title:
                merged[-1]["title"] = title
        else:
            merged.append({"title": title, "photos": photos})
    return merged


def section_description(title: str) -> str:
    """Narrative blurb under each photographic block (from survey report wording)."""
    t = title.lower()
    if "vertical" in t and "pre-clean" in t:
        return (
            "Mark location of photographs — vertical side shell (forward to midship) "
            "<b>before cleaning</b>. Fouling and coating condition documented for survey records."
        )
    if "vertical" in t and "post" in t:
        return (
            "Vertical side shell (forward to midship / midship to aft) <b>after cleaning</b> — "
            "condition following underwater hull cleaning operations."
        )
    if "flat bottom" in t and "pre" in t:
        return "Flat bottom (forward to midship) — <b>pre-cleaning</b> underwater inspection photographs."
    if "flat bottom" in t and "post" in t:
        return "Flat bottom — <b>post-cleaning</b> photographs after removal of marine growth."
    if "bilge" in t and "pre" in t:
        return "Bilge keels — leading and trailing edges, <b>before cleaning</b>."
    if "bilge" in t and "post" in t:
        return "Bilge keels — <b>after cleaning</b>."
    if "sea chest" in t and "before" in t:
        return "Sea chest gratings and intake grids — <b>before cleaning</b> (port, stbd, EFP as marked)."
    if "sea chest" in t and "after" in t:
        return "Sea chest gratings — <b>after cleaning</b>."
    if "propeller" in t and "pre" in t:
        return (
            "Propeller blades — suction and pressure sides, <b>pre-polishing</b> "
            "(Rubert scale comparator reference)."
        )
    if "propeller" in t and "post" in t:
        return "Propeller — <b>post-polishing</b> condition on all blades."
    if "boss cone" in t:
        return "Propeller boss cone — pre / post polishing."
    if "rudder" in t and "pre" in t:
        return "Rudder blade and pintle area — <b>pre-cleaning</b>."
    if "rudder" in t and "post" in t:
        return "Rudder — <b>post-cleaning</b>."
    return (
        f"Underwater photographs: <b>{title}</b>. "
        "Images extracted from the original survey report and embedded for reference."
    )
