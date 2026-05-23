import json
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parents[1] / "backend" / "storage" / "nauticai.db"
if not db.exists():
    print("no db at", db)
    raise SystemExit(1)

c = sqlite3.connect(db)
rows = c.execute(
    """
    SELECT id, vessel_guess, filename, ocr_text
    FROM images
    ORDER BY rowid DESC
    LIMIT 12
    """
).fetchall()
print("total images", c.execute("SELECT COUNT(*) FROM images").fetchone()[0])
for rid, guess, fn, ocr_raw in rows:
    print("---")
    print(rid, guess, fn)
    if ocr_raw:
        try:
            ocr = json.loads(ocr_raw) if isinstance(ocr_raw, str) else ocr_raw
            print("lines:", [x.get("text") for x in ocr[:10]])
        except Exception as e:
            print("ocr parse err", e)
