"""Extract all photographs from the BW BIRCH reference PDF into the cache.

Usage (from project root):
  python scripts/extract_reference_pdf.py
  python scripts/extract_reference_pdf.py "path/to/other.pdf"
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.pdf_extract import (
    default_birch_source_pdf,
    extract_pdf_photos,
    extraction_cache_dir,
)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else default_birch_source_pdf()
    if not src or not src.exists():
        print("Source PDF not found.")
        sys.exit(1)
    manifest = extract_pdf_photos(src, force_refresh=True)
    out_dir = extraction_cache_dir(src)
    print(f"Extracted {len(manifest.get('images') or [])} images.")
    print(f"Stored under: {out_dir.resolve()}")
    for block in manifest.get("sections") or []:
        print(f"  {len(block['paths']):3d}  {block['title'][:72]}")


if __name__ == "__main__":
    main()
