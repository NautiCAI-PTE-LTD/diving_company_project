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

## Inference speed (GPU)

1. Export ONNX once: `python scripts/export_onnx.py`
2. On a GPU server (L4/A10/Jetson): `python scripts/build_trt.py --fp16` → `Models/*.engine`
3. Or run `./deploy/gcp-l4/setup_gpu_models.sh` on the GCP L4 VM.
4. Restart API — `/api/system` should show `trt` or `onnx` backends on `cuda`.
3. Optional env vars:

| Variable | Default | Effect |
|----------|---------|--------|
| `NAUTICAI_INFERENCE_MAX_EDGE` | `1280` | Downscale 12 MP photos before CNNs (~3× faster) |
| `NAUTICAI_ANALYZE_CONCURRENCY` | `2` on GPU+ONNX | Two analyses at once on the GPU |
| `NAUTICAI_FP16` | `1` | FP16 autocast on CUDA PyTorch paths |
| `NAUTICAI_BACKEND` | `auto` | Set `onnx` to force ONNX Runtime |

OCR runs only on cover/nameplate candidates (not every underwater shot).

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
