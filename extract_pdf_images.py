"""Extract embedded images (not page-renders) from a PDF.

Usage:
    python extract_pdf_images.py "2024-1557 - WOLVERINE.pdf"

What it does:
    * Walks every page, enumerates image XObjects.
    * Pulls each image as raw bytes at its original resolution.
    * De-duplicates: identical xref + identical SHA-1 content is saved once.
    * Skips tiny images (< 200x200) because those are almost always
      template/letterhead icons, not photographic content.
    * Saves to ``<pdf>_images/`` next to the PDF.
"""
from __future__ import annotations
import sys, hashlib
from pathlib import Path

try:
    import fitz   # PyMuPDF
except ImportError:
    print("PyMuPDF not installed. Run: pip install pymupdf")
    sys.exit(1)

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


MIN_W, MIN_H   = 200, 200      # ignore tiny logos/icons
MIN_FILESIZE   = 8 * 1024      # < 8 KB → ignore (a 200x200 JPEG is typically much bigger)


def extract(pdf_path: Path) -> Path:
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")
    out_dir = pdf_path.with_suffix("")
    out_dir = out_dir.parent / (out_dir.name + "_images")
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    print(f"Opened: {pdf_path.name}  ({len(doc)} pages)")
    print(f"Output : {out_dir}")

    seen_xrefs: set[int] = set()
    seen_hash:  set[str] = set()
    n_saved = n_seen = n_small = n_dupe = 0
    biggest = (0, 0, "")

    for page_idx, page in enumerate(doc, start=1):
        for img in page.get_images(full=True):
            n_seen += 1
            xref = img[0]
            if xref in seen_xrefs:
                n_dupe += 1
                continue
            seen_xrefs.add(xref)

            try:
                info = doc.extract_image(xref)
            except Exception as e:
                print(f"  page {page_idx} xref {xref}: extract failed ({e})")
                continue

            data: bytes = info["image"]
            ext:  str   = info.get("ext", "png")
            w, h = info.get("width", 0), info.get("height", 0)

            if w < MIN_W or h < MIN_H or len(data) < MIN_FILESIZE:
                n_small += 1
                continue

            digest = hashlib.sha1(data).hexdigest()[:10]
            if digest in seen_hash:
                n_dupe += 1
                continue
            seen_hash.add(digest)

            name = f"page{page_idx:02d}_xref{xref:04d}_{w}x{h}_{digest}.{ext}"
            (out_dir / name).write_bytes(data)
            n_saved += 1
            if w * h > biggest[0] * biggest[1]:
                biggest = (w, h, name)

    doc.close()

    print(f"\nSeen   : {n_seen}")
    print(f"Saved  : {n_saved}")
    print(f"Tiny   : {n_small}  (skipped < {MIN_W}x{MIN_H} or < {MIN_FILESIZE//1024} KB)")
    print(f"Dupes  : {n_dupe}")
    if biggest[2]:
        print(f"Biggest: {biggest[0]}x{biggest[1]}  →  {biggest[2]}")
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python extract_pdf_images.py "path/to/file.pdf"')
        sys.exit(1)
    extract(Path(sys.argv[1]))
