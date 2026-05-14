import sys, fitz
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
d = fitz.open(r"Report_to_extract_images\24-1573 DALMA UHI & PP.pdf")
for pno in (3, 8, 29):
    page = d[pno-1]
    print(f"\n=== page {pno} ===")
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type", 0) != 0: continue
        for line in blk.get("lines", []):
            spans = line.get("spans", [])
            txt = "".join(s["text"] for s in spans)
            up = txt.upper()
            if any(k in up for k in ("CLEAN", "POLISH", "BEFORE", "AFTER")):
                bbox = line["bbox"]
                print(f"  bbox=({bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f})  text={txt!r}")
                for s in spans:
                    print(f"     span text={s['text']!r}  font={s.get('font','?')}")
