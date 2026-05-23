"""Extract survey PDF photos into vessel / data-1 / stage / section folders.

Layout::

    Report_to_extract_images/<vessel>/data-1/
        before/<section>/NNN_p<page>_<caption-slug>.jpg
        after/<section>/...
        other/<section>/...     # inspection, unknown stage, cofferdam, etc.

Run::

    python scripts/extract_structured_report_images.py
    python scripts/extract_structured_report_images.py path/to/one.pdf
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import fitz

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "Report_to_extract_images"

MIN_W, MIN_H, MIN_BYTES = 80, 80, 3 * 1024

# --- vessel folder names -------------------------------------------------
_VESSEL_ALIASES = (
    ("SILVERSTONE", "silverstone"),
    ("DALMA", "dalma"),
    ("WOLVERINE", "wolverine"),
    ("PATRIS", "patris"),
    ("ATALANTA", "atalanta"),
)


def vessel_folder_name(pdf: Path) -> str:
    upper = pdf.stem.upper()
    for key, slug in _VESSEL_ALIASES:
        if key in upper:
            return slug
    return re.sub(r"[^a-z0-9]+", "_", pdf.stem.lower()).strip("_")[:48] or "report"


# --- region detection (carried forward page by page) ---------------------
_REGION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"BOW\s+THRUSTER", re.I), "bow_thruster"),
    (re.compile(r"BOW\s*AREA", re.I), "bow"),
    (re.compile(r"PORT\s+VERTICAL", re.I), "port_vertical_side"),
    (re.compile(r"STBD\s+VERTICAL", re.I), "stbd_vertical_side"),
    (re.compile(r"VERTICAL\s+SIDE", re.I), "vertical_side"),
    (re.compile(r"FLAT\s+BOTTOM", re.I), "flat_bottom"),
    (re.compile(r"BILGE\s+KEEL", re.I), "bilge_keels"),
    (re.compile(r"SEA\s+CHEST", re.I), "sea_chest"),
    (re.compile(r"BOSS\s+CONE", re.I), "boss_cone"),
    (re.compile(r"PORT\s+SIDE\s+PROPELLER|PROPELLER", re.I), "propeller"),
    (re.compile(r"RUDDER", re.I), "rudder"),
    (re.compile(r"ROPE\s+GUARD", re.I), "rope_guard"),
    (re.compile(r"TAIL\s*SHAFT", re.I), "tailshaft"),
    (re.compile(r"PINTLE", re.I), "pintle"),
    (re.compile(r"COFFERDAM", re.I), "cofferdam"),
    (re.compile(r"\bEGCS\b", re.I), "egcs"),
    (re.compile(r"CATHODIC|ANODE", re.I), "cathodic_protection"),
    (re.compile(r"THRUSTER", re.I), "thruster"),
    (re.compile(r"STERN", re.I), "stern"),
    (re.compile(r"SKEG", re.I), "skeg"),
]


def detect_region_line(line: str) -> str | None:
    line = line.strip()
    if not line or len(line) > 100:
        return None
    if "REPORT" in line.upper() and "VESSEL" not in line.upper():
        if "UNDER" in line.upper() or "HULL" in line.upper() or "CCTV" in line.upper():
            return None
    for rx, slug in _REGION_PATTERNS:
        if rx.search(line):
            return slug
    return None


def carry_region(prev: str, page_lines: list[str]) -> str:
    region = prev
    for ln in page_lines:
        hit = detect_region_line(ln)
        if hit:
            region = hit
    return region


# --- stage (before / after / other) --------------------------------------
_STAGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bBEFORE\b[^A-Z]{0,40}CLEAN", re.I), "before"),
    (re.compile(r"\bAFTER\b[^A-Z]{0,40}CLEAN", re.I), "after"),
    (re.compile(r"\bPRIOR\s*TO\b[^A-Z]{0,40}CLEAN", re.I), "before"),
    (re.compile(r"\bPOST\b[^A-Z]{0,40}CLEAN", re.I), "after"),
    (re.compile(r"\bUPON\s*COMPLETION\b[^A-Z]{0,40}CLEAN", re.I), "after"),
    (re.compile(r"\bBEFORE\b[^A-Z]{0,40}POLISH", re.I), "before"),
    (re.compile(r"\bAFTER\b[^A-Z]{0,40}POLISH", re.I), "after"),
    (re.compile(r"\bINSPECTION\b", re.I), "other"),
    (re.compile(r"\bSURVEY\b", re.I), "other"),
]


def classify_stage_text(text: str) -> str | None:
    for rx, bucket in _STAGE_PATTERNS:
        if rx.search(text):
            return bucket
    return None


def page_stage(page) -> str:
    """Page-level stage from all text (fallback when per-image labels missing)."""
    blob = page.get_text()
    hits: list[str] = []
    for ln in blob.splitlines():
        tag = classify_stage_text(ln)
        if tag and tag not in hits:
            hits.append(tag)
    if "before" in hits and "after" not in hits:
        return "before"
    if "after" in hits and "before" not in hits:
        return "after"
    if hits == ["other"] or (len(hits) == 1 and hits[0] == "other"):
        return "other"
    if "before" in hits:
        return "before"
    if "after" in hits:
        return "after"
    return "other"


def collect_stage_labels(page) -> list[tuple[str, fitz.Rect]]:
    out: list[tuple[str, fitz.Rect]] = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type", 0) != 0:
            continue
        for line in blk.get("lines", []):
            txt = "".join(s["text"] for s in line.get("spans", []))
            tag = classify_stage_text(txt)
            if tag:
                out.append((tag, fitz.Rect(line["bbox"])))
    return out


def collect_image_rects(page) -> dict[int, list[fitz.Rect]]:
    by_xref: dict[int, list[fitz.Rect]] = {}
    try:
        for info in page.get_image_info(xrefs=True):
            x = info.get("xref", 0)
            r = fitz.Rect(info["bbox"])
            if x and not r.is_empty:
                by_xref.setdefault(x, []).append(r)
    except Exception:
        pass
    return by_xref


def nearest_stage(
    img_rect: fitz.Rect,
    labels: list[tuple[str, fitz.Rect]],
    page_fallback: str,
) -> str:
    if not labels:
        return page_fallback
    icx = (img_rect.x0 + img_rect.x1) / 2
    icy = (img_rect.y0 + img_rect.y1) / 2
    above: list[tuple[float, str]] = []
    others: list[tuple[float, str]] = []
    for tag, rect in labels:
        lcx = (rect.x0 + rect.x1) / 2
        lcy = (rect.y0 + rect.y1) / 2
        d = math.hypot(lcx - icx, lcy - icy)
        if rect.y1 <= img_rect.y0 + 8 and abs(lcx - icx) < 260:
            above.append((d, tag))
        else:
            others.append((d, tag))
    pool = above or others
    pool.sort()
    return pool[0][1]


def slug_caption(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip().lower())
    return (s[:max_len] or "photo").strip("_")


def save_as_jpg(data: bytes, ext: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if ext.lower() in ("jpg", "jpeg"):
        out_path.write_bytes(data)
        return
    try:
        from PIL import Image
        import io

        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.save(out_path, "JPEG", quality=92)
    except Exception:
        out_path.with_suffix(f".{ext}").write_bytes(data)


def extract_one_pdf(pdf_path: Path, *, force: bool = False) -> dict[str, Any]:
    vessel = vessel_folder_name(pdf_path)
    base = SRC_DIR / vessel / "data-1"
    if base.exists() and not force:
        # allow re-run with --force only
        pass

    doc = fitz.open(pdf_path)
    region = "general"
    seen_sha: set[str] = set()
    counters: Counter[str] = Counter()
    section_counters: Counter[tuple[str, str]] = Counter()
    rows: list[list[Any]] = []
    manifest_images: list[dict[str, Any]] = []

    for pno, page in enumerate(doc, start=1):
        lines = [ln.strip() for ln in page.get_text().splitlines() if ln.strip()]
        region = carry_region(region, lines)
        page_st = page_stage(page)
        stage_labels = collect_stage_labels(page)
        rects_by_xref = collect_image_rects(page)
        img_idx = 0

        for img in page.get_images(full=True):
            xref = img[0]
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue
            data: bytes = info["image"]
            ext: str = info.get("ext", "png")
            w, h = info.get("width", 0), info.get("height", 0)
            if w < MIN_W or h < MIN_H or len(data) < MIN_BYTES:
                continue

            sha = hashlib.sha1(data).hexdigest()
            if sha in seen_sha:
                continue
            seen_sha.add(sha)

            rects = rects_by_xref.get(xref) or [fitz.Rect(0, 0, page.rect.width, page.rect.height * 0.5)]
            stage = nearest_stage(rects[0], stage_labels, page_st)
            img_idx += 1
            section_counters[(stage, region)] += 1
            seq = section_counters[(stage, region)]
            counters[stage] += 1

            cap = ""
            for ln in lines:
                if classify_stage_text(ln) or detect_region_line(ln):
                    cap = ln
            fname = f"{seq:03d}_p{pno:02d}_{w}x{h}.jpg"
            out_dir = base / stage / region
            out_path = out_dir / fname
            save_as_jpg(data, ext, out_path)

            rel = out_path.relative_to(SRC_DIR).as_posix()
            rows.append([pdf_path.name, pno, xref, stage, region, w, h, len(data), rel, sha])
            manifest_images.append({
                "file": rel,
                "page": pno,
                "stage": stage,
                "section": region,
                "width": w,
                "height": h,
                "sha1": sha,
            })

    doc.close()

    manifest = {
        "source_pdf": pdf_path.name,
        "vessel_folder": vessel,
        "output_root": str(base.relative_to(SRC_DIR)),
        "counts": dict(counters),
        "images": manifest_images,
    }
    base.mkdir(parents=True, exist_ok=True)
    (base / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (base / "_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pdf", "page", "xref", "stage", "section", "w", "h", "bytes", "path", "sha1"])
        w.writerows(rows)

    return manifest


def main() -> None:
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        pdfs = [Path(a) if Path(a).is_absolute() else ROOT / a for a in args]
    else:
        pdfs = sorted(SRC_DIR.glob("*.pdf"))

    targets = [
        SRC_DIR / "24-1573 DALMA UHI & PP.pdf",
        SRC_DIR / "2024-1557 - WOLVERINE.pdf",
        SRC_DIR / "2024-1562 Patris, UHI , PP.pdf",
        SRC_DIR / "2024-1593 ATALANTA.pdf",
        SRC_DIR / "2024-1765 SILVERSTONE - COFFERDAM TO BLANK ECGS OB.pdf",
    ]
    if not args:
        pdfs = [p for p in targets if p.exists()]

    if not pdfs:
        print(f"No PDFs found under {SRC_DIR}")
        sys.exit(1)

    grand: Counter[str] = Counter()
    print(f"Output base: {SRC_DIR}/<vessel>/data-1/\n")

    for pdf in pdfs:
        if not pdf.exists():
            print(f"SKIP (missing): {pdf}")
            continue
        print(f"=== {pdf.name} → {vessel_folder_name(pdf)}/data-1/ ===")
        m = extract_one_pdf(pdf, force=force)
        c = m["counts"]
        total = sum(c.values())
        grand.update(c)
        for stage in ("before", "after", "other"):
            print(f"  {stage:8s} {c.get(stage, 0):4d}")
        print(f"  total    {total:4d}")
        # section breakdown
        sections: Counter[str] = Counter()
        for im in m["images"]:
            sections[im["section"]] += 1
        print("  sections:", ", ".join(f"{k}={v}" for k, v in sorted(sections.items())))

    print(f"\n=== GRAND TOTAL === before={grand['before']} after={grand['after']} other={grand['other']}")


if __name__ == "__main__":
    main()
