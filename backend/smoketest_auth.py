"""Multi-tenant smoke test:
  • register two companies (A and B)
  • verify data isolation (B can't see A's images)
  • analyse images for A, OCR a vessel photo, upload a logo
  • create a report and generate the PDF
"""
import json, sys, time, uuid, mimetypes
from pathlib import Path
import urllib.request

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent


# --------------- HTTP helpers -----------------------------------------------
def req(method: str, url: str, *, json_body=None, files=None, headers=None,
         params=None, timeout=180) -> dict:
    headers = dict(headers or {})
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif files is not None:
        boundary = "----nauticai" + uuid.uuid4().hex
        body = b""
        for name, (fname, fbody) in files.items():
            ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"{name}\"; filename=\"{fname}\"\r\n"
                     f"Content-Type: {ctype}\r\n\r\n").encode()
            body += fbody + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        data = body
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        data = None
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        text = resp.read().decode()
        return json.loads(text) if text else {}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def banner(t): print("\n" + "=" * 70 + f"\n  {t}\n" + "=" * 70)

EMAIL_A = f"alice-{uuid.uuid4().hex[:6]}@dive.example.com"
EMAIL_B = f"bob-{uuid.uuid4().hex[:6]}@subsea.example.com"

# --------------- 1. register two companies ---------------------------------
banner("Register company A")
a = req("POST", f"{BASE}/api/auth/register", json_body={
    "company_name": "Atlantic Dive Services",
    "full_name": "Alice Captain",
    "email": EMAIL_A,
    "password": "supersecret123",
    "tagline": "Marine inspection & cleaning since 1998",
})
tA = a["access_token"]
print(f"  user={a['user']['email']}  company={a['company']['company_name']}")

banner("Register company B")
b = req("POST", f"{BASE}/api/auth/register", json_body={
    "company_name": "Pacific Subsea Ltd",
    "full_name": "Bob Subsea",
    "email": EMAIL_B,
    "password": "differentsecret123",
})
tB = b["access_token"]
print(f"  user={b['user']['email']}  company={b['company']['company_name']}")

# --------------- 2. upload a logo for A ------------------------------------
banner("Upload logo for A")
logo_path = ROOT / "image.png"
if logo_path.exists():
    res = req("POST", f"{BASE}/api/settings/logo",
              files={"image": ("logo.png", logo_path.read_bytes())},
              headers=bearer(tA))
    print(f"  has_logo={res['has_logo']} url={res.get('logo_url')}")

# --------------- 3. analyse two photos for A -------------------------------
banner("Analyse 0.jpg as Bow + 2.jpg auto-routed (company A)")
img0 = (ROOT / "0.jpg").read_bytes()
img2 = (ROOT / "2.jpg").read_bytes()

ra = req("POST", f"{BASE}/api/analyze",
         files={"image": ("0.jpg", img0)}, headers=bearer(tA))
rb = req("POST", f"{BASE}/api/analyze",
         files={"image": ("2.jpg", img2)}, headers=bearer(tA))
print(f"  img1 region={ra['region']['id']}  species={ra['species']['top']}  fouling={ra['fouling_pct']}")
print(f"  img2 region={rb['region']['id']}  species={rb['species']['top']}  fouling={rb['fouling_pct']}")

# --------------- 4. OCR vessel name (persist) ------------------------------
banner("OCR vessel photo (persist=true) for A")
ocr = req("POST", f"{BASE}/api/ocr/vessel",
          files={"image": ("0.jpg", img0)},
          headers=bearer(tA), params={"persist": "true"})
print(f"  best_guess={ocr['best_guess']!r}  conf={ocr['best_confidence']:.2f}")
print(f"  vessel_image_id={ocr.get('image_id')}")

# --------------- 5. data isolation check -----------------------------------
banner("ISOLATION CHECK · B's image list should be empty")
imgs_a = req("GET", f"{BASE}/api/images", headers=bearer(tA))
imgs_b = req("GET", f"{BASE}/api/images", headers=bearer(tB))
print(f"  A images: {len(imgs_a)}")
print(f"  B images: {len(imgs_b)}")
assert len(imgs_a) >= 3 and len(imgs_b) == 0, "DATA LEAKED BETWEEN COMPANIES"
print("  → OK, data is isolated")

# --------------- 6. create report + generate PDF ---------------------------
banner("Create report for A and generate the PDF")
created = req("POST", f"{BASE}/api/reports", headers=bearer(tA), json_body={
    "vessel": {
        "vesselName": ocr.get("best_guess") or "GLEN COVE",
        "vesselType": "Tanker", "vesselClass": "BV",
        "jobNo": "2026-AUTH",
        "jobScope": "Under-Hull Cleaning & Propeller Polishing",
        "loa": "183", "draft": "11.2", "location": "Singapore Anchorage",
        "diveDate": "2026-05-13", "weather": "Cloudy", "sea": "Calm",
        "captain": "Capt. Demo", "diveSupervisor": "Alice Captain",
        "divers": "Eugenio, Arivu, Khairul", "boatCaptain": "Jabbar",
        "notes": "Multi-tenant smoke test",
        "extra": {"time_duration": {"day1": {
            "time_left_base": "07:00", "time_arrived_jobsite": "08:30",
            "dive_ops_started": "09:00", "dive_ops_completed": "16:30",
            "time_left_jobsite": "17:00", "time_arrived_base": "18:30",
        }}},
    },
    "image_ids": [ra["image_id"], rb["image_id"]],
    "region_inspections": {
        "Bow": {"overall_condition": "Good", "damage_observed": False,
                  "notes": "Light algae near waterline."},
    },
    "vessel_image_id": ocr.get("image_id") or "",
})
print(f"  report_id={created['id']}")
gen = req("POST", f"{BASE}/api/reports/{created['id']}/generate",
          headers=bearer(tA))
print(f"  pdf_url={gen['pdf_url']}")

# --------------- 7. cross-tenant access denied -----------------------------
banner("Cross-tenant access · B tries to read A's report")
try:
    req("GET", f"{BASE}/api/reports/{created['id']}", headers=bearer(tB))
    print("  !! UNEXPECTED: B could read A's report")
except urllib.error.HTTPError as e:
    print(f"  → correctly denied with HTTP {e.code}")

banner("DONE · multi-tenant auth flow verified")
