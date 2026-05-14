# NautiCAI · AI-assisted vessel hull inspection

> FastAPI backend + React (Vite) frontend that turns a batch of underwater
> diving photos into a polished marine-service PDF report, with automatic
> vessel-name OCR, hull-region clustering, before/after cleaning detection
> and fouling-species classification.

The system is built to run anywhere CUDA is available — from a developer
laptop with an RTX-30/40 GPU all the way down to a fan-cooled NVIDIA
**Jetson Orin Nano** at the edge. See [`deploy/jetson/README.md`](deploy/jetson/README.md)
for the production deployment recipe.

---

## Architecture at a glance

```
┌─────────────────────┐         multipart/form-data           ┌──────────────────────┐
│  React (Vite)       │ ───────────────────────────────────►  │  FastAPI / Uvicorn   │
│  Tailwind + Zustand │ ◄───────────────────────────────────  │  PostgreSQL/Supabase │
└─────────────────────┘            JSON + PDF                 │  or SQLite (dev)     │
                                                              │                      │
                                                              │  Inference pipeline  │
                                                              │  ┌────────────────┐  │
                                                              │  │ TRT / ONNX /   │  │
                                                              │  │ PyTorch native │  │
                                                              │  └────────────────┘  │
                                                              └──────────────────────┘
```

| Capability                      | Model                            | Backend (auto)               |
| ------------------------------- | -------------------------------- | ---------------------------- |
| Hull-region classifier          | Swin-Tiny @ 224 (11 classes)     | TensorRT → ONNX → PyTorch    |
| Fouling-species classifier      | EfficientNet-B0 (5 classes)      | TensorRT → ONNX → PyTorch    |
| Before / After cleaning split   | EfficientNetV2-B0 (Keras)        | TensorRT → ONNX → Keras      |
| Vessel-name OCR                 | EasyOCR (CRAFT + CRNN)           | PyTorch only                 |

The backend (`backend/inference/_runtime.py`) probes each checkpoint for a
matching `.engine` (TensorRT) or `.onnx` artefact next to the original
weights file and silently falls back to the native runtime if neither is
present. That keeps the developer experience zero-config while letting the
Jetson run at 4-5× the speed.

---

## Quick start (Windows / Linux dev)

```powershell
# 1. Clone
git clone https://github.com/NautiCAI-PTE-LTD/diving_company_project.git
cd diving_company_project

# 2. Drop the trained weights into Models/
#    (download Models_for_Jetson.zip from the team Drive — see Models/README.md)

# 3. Backend
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
copy backend\.env.example backend\.env   # then edit DATABASE_URL + JWT_SECRET
python -m uvicorn backend.main:app --reload --port 8000

# 4. Frontend (separate terminal)
cd frontend
npm ci
npm run dev    # http://localhost:5173
```

Confirm everything is wired up:

```powershell
Invoke-RestMethod http://localhost:8000/api/system | ConvertTo-Json -Depth 4
```

You should see `device: cuda`, `warmup: ready`, and `model_backends.*.backend: native`
(which is correct on the dev box — TRT only kicks in once you build engines).

---

## Jetson Orin Nano deployment

The repo includes a full end-to-end recipe in [`deploy/jetson/README.md`](deploy/jetson/README.md):

1. JetPack 6.x flash + system packages.
2. NVIDIA-built PyTorch wheel for aarch64+CUDA.
3. Export models to ONNX on the dev box (`scripts/export_onnx.py`).
4. Build TensorRT FP16 engines on the Jetson (`scripts/build_trt.py`).
5. nginx + systemd + auto-restart.

Expected throughput on Orin Nano @ MAXN: **~40-50 ms/image end-to-end** for
the three classifiers (4-5× faster than native PyTorch FP16).

---

## Repo layout

```
diving_company_project/
├── backend/                     FastAPI app
│   ├── inference/
│   │   ├── _runtime.py          ← TensorRT / ONNX / native selector
│   │   ├── region.py            ← hull-region classifier
│   │   ├── species.py           ← fouling-species classifier
│   │   ├── before_after.py      ← before/after binary
│   │   └── ocr.py               ← EasyOCR wrapper
│   ├── services/                ← analyze, cluster, pdf_report, video, storage
│   ├── schemas.py
│   ├── db.py
│   ├── main.py                  ← FastAPI app + endpoints
│   ├── config.py                ← paths, device detection, FP16 knobs
│   ├── requirements.txt         ← dev (Windows/Linux)
│   └── requirements-jetson.txt  ← aarch64 / JetPack 6.x runtime
├── frontend/                    React + Vite + Zustand + Tailwind
├── scripts/
│   ├── export_onnx.py           ← workstation-side ONNX export
│   └── build_trt.py             ← Jetson-side TensorRT engine builder
├── deploy/
│   └── jetson/
│       ├── README.md            ← full Jetson Orin Nano deployment guide
│       └── install.sh           ← bootstrap script
├── Models/                      ← weights (not in git — see Models/README.md)
└── README.md
```

---

## Environment variables (backend)

| Variable                | Default          | Meaning                                                            |
| ----------------------- | ---------------- | ------------------------------------------------------------------ |
| `DATABASE_URL`          | _(empty)_        | PostgreSQL/Supabase DSN. Falls back to SQLite if unset.            |
| `JWT_SECRET`            | `change-me-...`  | HS256 signing secret. **Must** be set in production.               |
| `NAUTICAI_DEVICE`       | `auto`           | `cpu` / `cuda` — override CUDA auto-detection.                     |
| `NAUTICAI_BACKEND`      | `auto`           | `auto` / `trt` / `onnx` / `native` — override the runtime picker.  |
| `NAUTICAI_FP16`         | `1`              | FP16 autocast on CUDA. Set to `0` to force FP32.                   |
| `NAUTICAI_MATMUL`       | `high`           | `torch.set_float32_matmul_precision` setting.                      |

---

## Licence

Proprietary — NautiCAI PTE LTD. All rights reserved.
