"""Peek the labels around photos in each PDF that didn't classify."""
import sys, re, fitz
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

src = Path("F:/Diving_company_project/Report_to_extract_images")

for pdf in src.glob("*.pdf"):
    print(f"\n############## {pdf.name} ##############")
    doc = fitz.open(pdf)
    for pno, page in enumerate(doc, start=1):
        text = page.get_text("text")
        n_img = len(page.get_images(full=True))
        if n_img < 2:
            continue
        # show all lines that look like a stage/condition label
        candidate_lines = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s: continue
            if (re.search(r"(BEFORE|PRIOR|AFTER|POST|FOLLOWING|UPON|DURING|PRE|POST)", s, re.I)
               or re.search(r"(CLEAN|FOULING|HULL|POLISH|CONDITION|STAGE|FINAL|ORIGINAL)", s, re.I)):
                if len(s) < 80:
                    candidate_lines.append(s)
        if candidate_lines:
            uniq = []
            for c in candidate_lines:
                if c not in uniq: uniq.append(c)
            print(f"  p{pno:02d} (imgs={n_img}):")
            for c in uniq[:8]:
                print(f"      | {c}")
        if pno > 25: break   # enough sampling
    doc.close()
