# NautiCAI backend on Google Cloud (NVIDIA L4)

Step-by-step guide to deploy the **FastAPI backend** on a **GCE GPU VM** (G2 + **NVIDIA L4**). The React UI can stay on Vercel, S3/CloudFront, or Firebase Hosting — point it at this API with `VITE_API_URL`.

---

## What you need (checklist)

| Item | Notes |
| ---- | ----- |
| GCP project | Billing enabled |
| GCS bucket | Stores model weights (~172 MB) — not in git |
| GCE VM | **g2-standard-4** (or **g2-standard-8**) + **NVIDIA L4**, Ubuntu 22.04 |
| Postgres | **Supabase** or **Cloud SQL** — set `DATABASE_URL` in `backend/.env` |
| JWT secret | Random 64+ char string |
| Model zip | From Drive — see `Models/README.md` |

---

## Requirement files (Python)

Install **on the L4 VM** (not on your laptop for production GPU paths):

| File | Purpose |
| ---- | ------- |
| `backend/requirements.txt` | Core API: FastAPI, PyTorch, TensorFlow, EasyOCR, ReportLab, Postgres, etc. |
| `backend/requirements-gpu.txt` | Adds `onnxruntime-gpu`, ONNX export tools — **use on the L4 VM** |

```bash
pip install -r backend/requirements.txt -r backend/requirements-gpu.txt
```

`deploy/gcp-l4/setup_gpu_models.sh` runs both files for you.

**Do not use** the root `Dockerfile` for L4 — it installs **CPU-only** PyTorch. On GCP L4, run **native Python + venv** (this guide) or build a separate GPU image later.

**Optional (fastest inference):** system [TensorRT 10 for CUDA 12](https://developer.nvidia.com/tensorrt) + `pip install pycuda` — then `setup_gpu_models.sh` builds `Models/*.engine`.

---

## GCS bucket — what to upload

Create one bucket (example name: `nauticai-prod-artifacts`). Region: same as the VM (e.g. `asia-southeast1`).

### Folder layout

```text
gs://YOUR_BUCKET/
├── models/                          # REQUIRED — upload from your PC once
│   ├── Ship_classification_v2.pth   (~107 MB)
│   ├── Before_and_after_v2.keras    (~49 MB)
│   └── species_classifier_bundle.pt (~16 MB)
└── models-built/                    # OPTIONAL — after first GPU setup on a VM
    ├── Ship_classification_v2.onnx
    ├── Ship_classification_v2.engine
    ├── Before_and_after_v2.onnx
    ├── Before_and_after_v2.engine
    ├── species_classifier_bundle.onnx
    └── species_classifier_bundle.engine
```

`models-built/` saves 10–20 minutes on new VMs (skip ONNX export + TensorRT build). Generate it once with `setup_gpu_models.sh`, then:

```bash
gsutil -m cp Models/*.onnx Models/*.engine gs://YOUR_BUCKET/models-built/
```

### Upload from Windows (PowerShell)

```powershell
cd F:\Diving_company_project
.\deploy\gcp-l4\upload-models-to-gcs.ps1 -Bucket YOUR_BUCKET
```

Or manually:

```powershell
gcloud storage cp Models\Ship_classification_v2.pth gs://YOUR_BUCKET/models/
gcloud storage cp Models\Before_and_after_v2.keras gs://YOUR_BUCKET/models/
gcloud storage cp Models\species_classifier_bundle.pt gs://YOUR_BUCKET/models/
```

**Not required in the bucket:** application code (use `git clone` on the VM), uploads/PDFs (live on VM disk or Postgres), frontend static files.

---

## Step 1 — Create the GCS bucket

```bash
export PROJECT_ID=your-gcp-project
export REGION=asia-southeast1
export BUCKET=nauticai-prod-artifacts

gcloud config set project $PROJECT_ID
gcloud storage buckets create gs://$BUCKET --location=$REGION --uniform-bucket-level-access
```

Upload models (see above) before starting the VM.

---

## Step 2 — Create the L4 VM

**Console:** Compute Engine → **Create instance**

| Setting | Value |
| ------- | ----- |
| Series | **G2** |
| GPU | **1 × NVIDIA L4** |
| Machine type | **g2-standard-4** (4 vCPU, 16 GB) or **g2-standard-8** for heavier PDF batches |
| Boot disk | Ubuntu **22.04 LTS**, **50 GB+** |
| Firewall | Allow **HTTP** or custom **TCP 8000** (lock down to your IP in production) |

**CLI example:**

```bash
gcloud compute instances create nauticai-l4 \
  --zone=${REGION}-a \
  --machine-type=g2-standard-4 \
  --accelerator=type=nvidia-l4,count=1 \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=50GB \
  --maintenance-policy=TERMINATE \
  --tags=http-server
```

SSH:

```bash
gcloud compute ssh nauticai-l4 --zone=${REGION}-a
```

### NVIDIA driver

On first boot, either enable **“Install NVIDIA GPU driver”** in the console, or:

```bash
sudo apt-get update
sudo apt-get install -y linux-headers-$(uname -r) nvidia-driver-535
sudo reboot
```

After reboot:

```bash
nvidia-smi   # must show NVIDIA L4, driver 535+
```

---

## Step 3 — Bootstrap the VM

```bash
git clone https://github.com/YOUR_ORG/diving_company_project.git /opt/nauticai/app
cd /opt/nauticai/app
chmod +x deploy/gcp-l4/bootstrap-gce.sh deploy/gcp-l4/sync-from-gcs.sh
./deploy/gcp-l4/bootstrap-gce.sh
```

Log out and back in if the script added you to the `docker` group (only needed if you use Docker later).

---

## Step 4 — Copy models from GCS

```bash
export GCS_BUCKET=nauticai-prod-artifacts
cd /opt/nauticai/app
./deploy/gcp-l4/sync-from-gcs.sh
```

This downloads `gs://BUCKET/models/*` into `/opt/nauticai/Models/`. If `models-built/` exists in the bucket, it also copies `.onnx` / `.engine` files.

---

## Step 5 — GPU model setup (ONNX + optional TensorRT)

```bash
cd /opt/nauticai/app
source .venv/bin/activate
./deploy/gcp-l4/setup_gpu_models.sh
```

Skips export/TRT if `.onnx` / `.engine` already exist from GCS.

Verify:

```bash
python scripts/verify_gpu_inference.py
curl -s http://127.0.0.1:8000/api/system   # after API is running
```

Expect backends `trt` or `onnx` with `device: cuda`.

---

## Step 6 — Production environment

```bash
cp deploy/gcp-l4/env.production.example backend/.env
nano backend/.env
```

Set at minimum:

```env
DATABASE_URL=postgresql://user:pass@host:5432/dbname?sslmode=require
JWT_SECRET=<paste output of: python3 -c "import secrets; print(secrets.token_urlsafe(64))">
```

Copy the rest from `deploy/gcp-l4/env.production.example` (`NAUTICAI_DEVICE=cuda`, `NAUTICAI_GPU_PROFILE=l4`, etc.).

**Database:** use Supabase (easiest) or Cloud SQL. Leave `DATABASE_URL` empty only for dev SQLite — not for production.

---

## Step 7 — Run the API

### Manual test

```bash
cd /opt/nauticai/app
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

From your PC (replace with VM external IP):

```bash
curl http://VM_EXTERNAL_IP:8000/api/health
```

### systemd (recommended)

```bash
sudo cp deploy/gcp-l4/nauticai-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nauticai-api
sudo systemctl status nauticai-api
journalctl -u nauticai-api -f
```

---

## Step 8 — Firewall and HTTPS

**Restrict port 8000** in VPC firewall to your office IP or put **HTTPS** in front:

- **Google Cloud Load Balancer** + managed SSL, or  
- **Caddy / nginx** on the VM terminating TLS → `127.0.0.1:8000`

OpenAPI docs: `https://api.yourdomain.com/docs`

---

## Step 9 — Connect the frontend

Build the React app with your API URL:

```bash
cd frontend
VITE_API_URL=https://api.yourdomain.com npm run build
```

Deploy `frontend/dist/` to your static host. CORS is currently `*` in `backend/main.py` — tighten before public launch if needed.

---

## VM disk layout (reference)

```text
/opt/nauticai/
├── app/                    # git clone
│   ├── Models/             # symlink or copy → ../Models
│   ├── backend/storage/    # uploads + PDFs (persist on disk)
│   └── .venv/
└── Models/                 # weights + .onnx + .engine (from GCS + setup script)
```

Optional **persistent disk** mounted at `/opt/nauticai` so uploads survive VM recreate.

---

## Environment reference (L4)

| Variable | Recommended |
| -------- | ----------- |
| `NAUTICAI_DEVICE` | `cuda` |
| `NAUTICAI_GPU_PROFILE` | `l4` |
| `NAUTICAI_BACKEND` | `auto` |
| `NAUTICAI_ANALYZE_CONCURRENCY` | `4` |
| `NAUTICAI_FP16` | `1` |
| `DATABASE_URL` | Postgres connection string |
| `JWT_SECRET` | Long random secret |

---

## Troubleshooting

| Problem | Fix |
| ------- | --- |
| `nvidia-smi` fails | Install driver 535+, reboot |
| `ONNX Runtime CUDA EP available=False` | `pip install onnxruntime-gpu`, check `nvidia-smi` |
| Missing model file | Upload to GCS `models/`, run `sync-from-gcs.sh` |
| Slow first request | Wait for warmup; check `/api/system` `warmup_ready` |
| CUDA OOM | Set `NAUTICAI_ANALYZE_CONCURRENCY=2` |
| API unreachable | Open firewall TCP 8000; check `systemctl status nauticai-api` |

---

## Target performance (L4)

| Backend | Typical latency per photo (3 models) |
| ------- | ----------------------------------- |
| TensorRT `.engine` | ~15–35 ms |
| ONNX Runtime CUDA | ~25–50 ms |
| Native PyTorch only | ~80–150 ms |

---

## Related files

| Path | Role |
| ---- | ---- |
| `backend/requirements.txt` | Base dependencies |
| `backend/requirements-gpu.txt` | GPU / ONNX CUDA extras |
| `deploy/gcp-l4/setup_gpu_models.sh` | Export ONNX + build TRT on VM |
| `deploy/gcp-l4/env.production.example` | Template `backend/.env` |
| `deploy/gcp-l4/upload-models-to-gcs.ps1` | Upload weights from Windows |
| `deploy/gcp-l4/sync-from-gcs.sh` | Download weights on VM |
| `deploy/gcp-l4/bootstrap-gce.sh` | apt packages + venv |
| `Models/README.md` | Model file list |
