"""Build a Before/After training set from West Squadron dive reports.

We classify each embedded image by matching it to the nearest text
label on the same page.  Different reports use different wording, so
we recognise BOTH "Before/After Cleaning" (hull cleaning) AND
"Before/After Polishing" (propeller polishing) and route them to
separate buckets so they don't pollute each other during training.

Output layout (under ``Report_to_extract_images/extracted/``):

    before/                  ← hull "Before Cleaning"
    after/                   ← hull "After Cleaning"
    before_polishing/        ← propeller "Before Polishing"
    after_polishing/         ← propeller "After Polishing"
    other/<PDF stem>/        ← pages with photos but no detectable label
    _manifest.csv            ← every decision + distance metric

Run:
    python extract_before_after.py
"""
from __future__ import annotations
import sys, csv, hashlib, re, math
from pathlib import Path
from collections import Counter

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

import fitz   # PyMuPDF

# ---------- config ---------------------------------------------------
SRC_DIR = Path("F:/Diving_company_project/Report_to_extract_images")
DST_DIR = SRC_DIR / "extracted"

# Recognise text labels with a single tagged regex per category.
# Ordering matters: try CLEAN first (more specific), then POLISH.
LABEL_PATTERNS = [
    # (regex, bucket)
    (re.compile(r"\bBEFORE\b[^A-Z]{0,40}CLEAN",   re.IGNORECASE), "before"),
    (re.compile(r"\bAFTER\b[^A-Z]{0,40}CLEAN",    re.IGNORECASE), "after"),
    (re.compile(r"\bPRIOR\s*TO\b[^A-Z]{0,40}CLEAN", re.IGNORECASE), "before"),
    (re.compile(r"\bPOST\b[^A-Z]{0,40}CLEAN",     re.IGNORECASE), "after"),
    (re.compile(r"\bUPON\s*COMPLETION\b[^A-Z]{0,40}CLEAN", re.IGNORECASE), "after"),
    # Polishing variants → dedicated buckets
    (re.compile(r"\bBEFORE\b[^A-Z]{0,40}POLISH",  re.IGNORECASE), "before_polishing"),
    (re.compile(r"\bAFTER\b[^A-Z]{0,40}POLISH",   re.IGNORECASE), "after_polishing"),
]

# Don't bother extracting tiny logos/icons.
MIN_W, MIN_H, MIN_BYTES = 80, 80, 3 * 1024


# ---------- helpers --------------------------------------------------
def classify_line(text: str) -> str | None:
    """Return bucket name (or None) for one text-line string."""
    for rx, bucket in LABEL_PATTERNS:
        if rx.search(text):
            return bucket
    return None


def collect_labels(page) -> list[tuple[str, fitz.Rect]]:
    """All before/after text bboxes on this page (any bucket)."""
    out: list[tuple[str, fitz.Rect]] = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type", 0) != 0:    # 0 = text
            continue
        for line in blk.get("lines", []):
            txt = "".join(s["text"] for s in line.get("spans", []))
            tag = classify_line(txt)
            if tag:
                out.append((tag, fitz.Rect(line["bbox"])))
    return out


def collect_image_rects(page) -> dict[int, list[fitz.Rect]]:
    """Map xref → list of placement bboxes (an image can be drawn twice)."""
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


def nearest_label(img: fitz.Rect,
                  labels: list[tuple[str, fitz.Rect]]) -> tuple[str | None, float]:
    """Find the closest label whose centre is above or in the same column."""
    if not labels:
        return None, -1
    icx, icy = (img.x0 + img.x1) / 2, (img.y0 + img.y1) / 2
    above, others = [], []
    for tag, rect in labels:
        lcx, lcy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        d = math.hypot(lcx - icx, lcy - icy)
        # "Above & same column" is the strongest signal.
        if rect.y1 <= img.y0 + 5 and abs(lcx - icx) < 240:
            above.append((d, tag))
        else:
            others.append((d, tag))
    pool = above or others
    pool.sort()
    return pool[0][1], pool[0][0]


# ---------- main -----------------------------------------------------
def main():
    if not SRC_DIR.exists():
        print(f"Source folder not found: {SRC_DIR}"); sys.exit(1)
    pdfs = sorted(SRC_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {SRC_DIR}"); sys.exit(1)

    buckets = ("before", "after", "before_polishing", "after_polishing")
    for b in buckets:
        (DST_DIR / b).mkdir(parents=True, exist_ok=True)
    (DST_DIR / "other").mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    grand = Counter()
    rows = [["pdf", "page", "xref", "bucket", "dist",
             "w", "h", "bytes", "out_path", "sha1"]]

    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        doc = fitz.open(pdf)
        per_pdf = Counter()
        other_dir = DST_DIR / "other" / pdf.stem.replace(" ", "_")
        other_dir.mkdir(parents=True, exist_ok=True)

        for pno, page in enumerate(doc, start=1):
            labels = collect_labels(page)
            rects_by_xref = collect_image_rects(page)

            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                data = info["image"]
                w, h = info.get("width", 0), info.get("height", 0)
                ext  = info.get("ext", "png")
                if w < MIN_W or h < MIN_H or len(data) < MIN_BYTES:
                    continue
                sha = hashlib.sha1(data).hexdigest()
                if sha in seen:
                    continue
                seen.add(sha)

                rects = rects_by_xref.get(xref) or [page.rect]
                tag, dist = nearest_label(rects[0], labels)
                if tag is None:
                    out_dir = other_dir
                    bucket  = "other"
                else:
                    out_dir = DST_DIR / tag
                    bucket  = tag

                name = (f"{pdf.stem.replace(' ', '_')}_p{pno:02d}"
                        f"_x{xref:04d}_{w}x{h}_{sha[:8]}.{ext}")
                (out_dir / name).write_bytes(data)
                per_pdf[bucket] += 1
                grand[bucket]   += 1
                rows.append([pdf.name, pno, xref, bucket, f"{dist:.1f}",
                             w, h, len(data),
                             str((out_dir / name).relative_to(DST_DIR)),
                             sha])
        doc.close()
        print(f"  before={per_pdf['before']:4d}  after={per_pdf['after']:4d}"
              f"  before_polish={per_pdf['before_polishing']:4d}  after_polish={per_pdf['after_polishing']:4d}"
              f"  other={per_pdf['other']:4d}")

    with (DST_DIR / "_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    print("\n=== TOTAL ===")
    for b in ("before", "after", "before_polishing", "after_polishing", "other"):
        print(f"  {b:18s} {grand[b]:4d}")
    print(f"  unique total       {len(seen):4d}")
    print(f"  manifest: {DST_DIR/'_manifest.csv'}")


if __name__ == "__main__":
    main()
