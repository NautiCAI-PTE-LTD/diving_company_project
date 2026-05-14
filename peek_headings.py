"""Quick probe: print every page's text + image count for one PDF so we
can see what the cleaning-stage headings actually look like."""
from __future__ import annotations
import sys, re
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

import fitz

if len(sys.argv) < 2:
    print("usage: python peek_headings.py <pdf>"); sys.exit(1)

doc = fitz.open(sys.argv[1])
PATTERNS = re.compile(r"(BEFORE|PRIOR\s*TO|AFTER|POST|FOLLOWING|UPON\s*COMPLETION)[^\n]{0,40}(CLEAN|CLEANING|CLEAN-UP|TREAT)",
                       re.IGNORECASE)

for i, page in enumerate(doc, 1):
    text = page.get_text("text").strip()
    n_imgs = len(page.get_images(full=True))
    hits = PATTERNS.findall(text)
    head_lines = [ln for ln in text.splitlines()[:6] if ln.strip()]
    flag = " [BEFORE/AFTER MATCH]" if hits else ""
    if n_imgs == 0 and not hits and i > 5:
        continue
    print(f"\n--- page {i}  imgs={n_imgs}{flag} ---")
    for ln in head_lines:
        print(f"  > {ln[:90]}")
    if hits:
        for h in hits:
            print(f"  ⇨ matched: {h}")
doc.close()
