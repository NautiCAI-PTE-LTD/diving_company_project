"""End-to-end smoke test: hits the running backend at http://127.0.0.1:8000."""
import json
import sys
import time
from pathlib import Path
import urllib.request, urllib.error
import mimetypes
import uuid

# Force UTF-8 stdout on Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent


def post_multipart(url: str, files: dict, fields: dict | None = None) -> dict:
    boundary = "----nauticai" + uuid.uuid4().hex
    body = b""
    for k, v in (fields or {}).items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    for k, (filename, data) in files.items():
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{filename}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def banner(t: str) -> None:
    print("\n" + "=" * 70 + f"\n  {t}\n" + "=" * 70)


# ----------------------------------------------------------------- 1. health ----
banner("/api/health")
print(get_json(f"{BASE}/api/health"))

banner("/api/meta")
m = get_json(f"{BASE}/api/meta")
print("regions:", [r["id"] for r in m["regions"]])
print("species:", [s["id"] for s in m["species"]])
print("models :", [m_["name"] for m_ in m["models"]])

# ----------------------------------------------------------------- 2. analyze ----
banner("/api/analyze · using 0.jpg as a hull-region surrogate")
img0 = (ROOT / "0.jpg").read_bytes()
res = post_multipart(f"{BASE}/api/analyze",
                     files={"image": ("0.jpg", img0)},
                     fields={"region_hint": "Bow"})
print(json.dumps({k: v for k, v in res.items() if k != "species"}, indent=2))
print("species top:", res["species"]["top"], "→", res["species"]["top_display"])
img0_id = res["image_id"]

banner("/api/analyze · 2.jpg without region hint (auto-routing via Swin)")
img2 = (ROOT / "2.jpg").read_bytes()
res2 = post_multipart(f"{BASE}/api/analyze", files={"image": ("2.jpg", img2)})
print("region:", res2["region"], "stage:", res2["stage"], "fouling%:", res2["fouling_pct"])
img2_id = res2["image_id"]

# ----------------------------------------------------------------- 3. ocr ----
banner("/api/ocr/vessel · 0.jpg (GLEN COVE, sunset)")
ocr0 = post_multipart(f"{BASE}/api/ocr/vessel?persist=true", files={"image": ("0.jpg", img0)})
print(json.dumps(ocr0, indent=2))

banner("/api/ocr/vessel · 2.jpg (GLEN COVE / MAJURO)")
ocr2 = post_multipart(f"{BASE}/api/ocr/vessel?persist=true", files={"image": ("2.jpg", img2)})
print(json.dumps(ocr2, indent=2))

# ----------------------------------------------------------------- 3b. settings + logo ----
banner("/api/settings · save + logo upload")
req = urllib.request.Request(
    f"{BASE}/api/settings",
    data=json.dumps({
        "company_name":    "Atlantic Dive Services",
        "company_tagline": "Marine inspection & hull cleaning since 1998",
        "company_address": "12 Harbour Road, Singapore",
        "company_phone":   "+65 1234 5678",
        "company_email":   "ops@atlanticdive.test",
        "company_website": "https://atlanticdive.test",
        "report_footer":   "Powered by NautiCAI",
        "has_logo": False, "logo_url": None,
    }).encode(),
    headers={"Content-Type": "application/json"}, method="PUT",
)
with urllib.request.urlopen(req, timeout=15) as resp:
    print("PUT /api/settings →", json.loads(resp.read().decode())["company_name"])

logo_path = ROOT / "image.png"
if logo_path.exists():
    sb = post_multipart(f"{BASE}/api/settings/logo",
                        files={"image": ("logo.png", logo_path.read_bytes())})
    print("POST /api/settings/logo → has_logo:", sb["has_logo"])

# ----------------------------------------------------------------- 4. report ----
banner("/api/reports · create + generate PDF")
created = post_json(f"{BASE}/api/reports", {
    "vessel": {
        "vesselName": ocr2.get("best_guess") or "GLEN COVE",
        "vesselType": "Tanker", "vesselClass": "BV",
        "jobNo": "2024-9999", "jobScope": "Under-Hull Cleaning & Propeller Polishing",
        "loa": "183", "draft": "11.2", "location": "Singapore Anchorage",
        "diveDate": "2024-08-31", "weather": "Cloudy", "sea": "Calm",
        "visibility": "1.2", "tide": "0.4",
        "captain": "Capt. Demo", "diveSupervisor": "Fahmi",
        "divers": "Eugenio, Arivu, Khairul", "boatCaptain": "Jabbar",
        "notes": "Smoke test from backend/smoketest.py",
        "extra": {"time_duration": {
            "day1": {
                "time_left_base": "07:00",
                "time_arrived_jobsite": "08:30",
                "dive_ops_started": "09:00",
                "dive_ops_completed": "16:30",
                "time_left_jobsite": "17:00",
                "time_arrived_base": "18:30",
                "remarks": "Calm sea, smooth ops.",
            },
        }},
    },
    "image_ids": [img0_id, img2_id],
    "region_inspections": {
        "Bow": {"inspection_done": True, "overall_condition": "Good",
                 "damage_observed": False, "notes": "Minor algae spotted near waterline."},
        "Propeller": {"inspection_done": True, "overall_condition": "Good",
                       "damage_observed": False,
                       "propeller": {"count": "1", "blade_count": "4", "diameter": "5200",
                                       "blade_type": "Fixed", "oxidised_pct": "70",
                                       "rubert_scale": "B", "pitting": False,
                                       "cavitation": False, "cracks": False,
                                       "previous_repairs": False,
                                       "cement_covers_intact": True, "bolts_intact": True,
                                       "cone_bolt_intact": True}},
        "Radder": {"inspection_done": True, "overall_condition": "Good",
                    "damage_observed": False,
                    "rudder": {"count": "1", "type": "Semi-Balanced",
                                "plug_intact": True, "anodes": True,
                                "depletion": "20%"}},
    },
    "vessel_image_id": ocr2.get("image_id") or "",
})
print("created:", created["id"], "status:", created["status"])

gen = post_json(f"{BASE}/api/reports/{created['id']}/generate", {})
print("pdf:", gen)

stats = get_json(f"{BASE}/api/stats")
print("\nKPIs ·",
      f"vessels={stats['vessels_inspected']}, images={stats['images_processed']},",
      f"reports={stats['reports_generated']}, avg_fouling={stats['avg_fouling']}")
print("activity:", stats["activity"])
print("species_mix:", stats["species_mix"])
print("region_index:", stats["region_index"])

print("\nDONE — open the generated PDF at backend/storage/reports/" + created["id"] + ".pdf")
