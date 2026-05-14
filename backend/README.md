# NautiCAI Backend

FastAPI service that powers the React dashboard with four AI capabilities:

| Capability | Model | Endpoint |
|---|---|---|
| Hull-region clustering (Bow / Bilge keels / Propeller / …) | Swin-Tiny — `Models/Ship_classification_v2.pth` | `POST /api/analyze` |
| Before / After cleaning split inside the report | EfficientNetV2-B0 — `Models/Before_and_after_v2.keras` | runs inside `/analyze` |
| Fouling-species classification (algae / barnacles / …) | EfficientNet-B0 — `Models/species_classifier_bundle.pt` | runs inside `/analyze` |
| Vessel-name extraction from a deck photo | EasyOCR | `POST /api/ocr/vessel` |

Plus full report CRUD and PDF generation that mirrors every section of
`marine_service_report (2).pdf`.

## Run

```powershell
# from project root (f:\Diving_company_project)
pip install -r backend\requirements.txt   # most are already installed
python -m uvicorn backend.main:app --reload --port 8000
# OR
backend\run.bat
```

Open <http://localhost:8000/docs> for the live OpenAPI explorer.

## Endpoints (overview)

- `GET  /api/health`
- `GET  /api/meta`                       — class names, model info
- `POST /api/analyze`                    — multipart `image` + `region_hint?` → AI tags
- `POST /api/ocr/vessel`                 — multipart `image` → vessel-name candidates
- `GET  /api/images`                     — list uploaded images
- `GET  /api/images/{id}/file`           — raw bytes
- `DELETE /api/images/{id}`              — remove
- `POST /api/reports`                    — `{vessel, image_ids}` → new report
- `GET  /api/reports`                    — list / filter by status / search
- `GET  /api/reports/{id}`               — detail with clusters
- `PATCH /api/reports/{id}`              — update vessel info / images / status
- `DELETE /api/reports/{id}`             — remove
- `POST /api/reports/{id}/generate`      — build PDF
- `GET  /api/reports/{id}/pdf`           — download PDF
- `GET  /api/stats`                      — KPIs for the dashboard

## Storage layout

```
backend/storage/
├── nauticai.db            ← SQLite DB
├── uploads/               ← raw uploaded images (uuid.jpg)
└── reports/               ← generated PDFs (NCAI-XXXXXX.pdf)
```
