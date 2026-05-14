"""Dump every non-empty text line from one PDF — find what wording the
report actually uses near image grids."""
import sys, fitz, re
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

p = Path(sys.argv[1])
doc = fitz.open(p)
print(f"\n#### {p.name}  ({len(doc)} pages) ####")
for pno, page in enumerate(doc, 1):
    n_img = len(page.get_images(full=True))
    text  = page.get_text("text")
    has_relevant = re.search(r"(BEFORE|AFTER|PRIOR|POST|POLISH|CLEAN|FOULING|FINAL|INITIAL|RESULT)",
                             text, re.I)
    if n_img == 0 and not has_relevant: continue
    print(f"\n----- p{pno:02d}  imgs={n_img} -----")
    for ln in (ln.strip() for ln in text.splitlines()):
        if ln and len(ln) < 100:
            print(f"  {ln[:96]}")
doc.close()
