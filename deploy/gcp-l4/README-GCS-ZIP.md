# Deploy backend with one GCS zip (L4 GPU)

Use this flow when you have created the **L4 GCE instance** and want a **single zip** in Cloud Storage.

---

## Part 1 — On your Windows PC

### 1. Build the zip (~170 MB)

```powershell
cd F:\Diving_company_project
.\deploy\gcp-l4\build-l4-gcs-bundle.ps1
```

Output:

```text
deploy\gcp-l4\dist\nauticai-l4-gcs-bundle.zip
```

### 2. What is inside the zip

| Path in zip | Purpose |
| ----------- | ------- |
| `models/Ship_classification_v2.pth` | Hull region classifier |
| `models/Before_and_after_v2.keras` | Before/after classifier |
| `models/species_classifier_bundle.pt` | Species classifier |
| `models/*.onnx` | Optional — only if you already exported ONNX locally |
| `deploy/gcp-l4/install-on-vm.sh` | Full install on the VM |
| `deploy/gcp-l4/setup_gpu_models.sh` | Used by install script |
| `deploy/gcp-l4/env.production.example` | Template for `backend/.env` |
| `deploy/gcp-l4/nauticai-api.service` | systemd unit |
| `requirements.txt` + `requirements-gpu.txt` | Reference copies |

**Not in the zip:** application source code — the VM clones your **Git repo** (or you clone manually first).

### 3. Create bucket and upload

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

gcloud storage buckets create gs://nauticai-prod-artifacts --location=asia-southeast1

gcloud storage cp deploy\gcp-l4\dist\nauticai-l4-gcs-bundle.zip gs://nauticai-prod-artifacts/
```

---

## Part 2 — On the L4 VM (SSH)

### 1. SSH in

```bash
gcloud compute ssh YOUR_INSTANCE_NAME --zone=YOUR_ZONE
```

Check GPU:

```bash
nvidia-smi
```

### 2. Clone the app (once)

```bash
sudo mkdir -p /opt/nauticai
sudo chown -R $USER:$USER /opt/nauticai
git clone https://github.com/YOUR_ORG/diving_company_project.git /opt/nauticai/app
cd /opt/nauticai/app
git pull   # latest deploy scripts
```

### 3. Run full install from GCS zip

```bash
export GCS_BUCKET=nauticai-prod-artifacts
export GCS_ZIP=nauticai-l4-gcs-bundle.zip
# optional if not cloned above:
# export REPO_URL=https://github.com/YOUR_ORG/diving_company_project.git

chmod +x deploy/gcp-l4/install-on-vm.sh
./deploy/gcp-l4/install-on-vm.sh
```

This will:

1. Download and unzip your bundle from GCS  
2. Copy models → `/opt/nauticai/Models/`  
3. Create Python venv + install `requirements.txt` + `requirements-gpu.txt`  
4. Export ONNX (+ TensorRT if installed) on the GPU  
5. Write `backend/.env` from template (auto `JWT_SECRET`)  
6. Start **systemd** service `nauticai-api` on port **8000**

### 4. Set database (required)

```bash
nano /opt/nauticai/app/backend/.env
```

Set:

```env
DATABASE_URL=postgresql://user:pass@host:5432/dbname?sslmode=require
```

Restart:

```bash
sudo systemctl restart nauticai-api
```

### 5. Open firewall

In GCP console → VPC firewall → allow **TCP 8000** to your IP (or use HTTPS load balancer later).

Test:

```bash
curl http://VM_EXTERNAL_IP:8000/api/health
curl http://VM_EXTERNAL_IP:8000/api/system
```

---

## Part 3 — After backend is live (AWS UI later)

When the API URL is stable (e.g. `https://api.yourdomain.com`):

```bash
cd frontend
VITE_API_URL=https://api.yourdomain.com npm run build
# deploy dist/ to S3 + CloudFront
```

---

## Quick reference

| Item | Value |
| ---- | ----- |
| Zip name | `nauticai-l4-gcs-bundle.zip` |
| Models on VM | `/opt/nauticai/Models/` |
| App | `/opt/nauticai/app/` |
| Env file | `/opt/nauticai/app/backend/.env` |
| Service | `sudo systemctl status nauticai-api` |
| Logs | `journalctl -u nauticai-api -f` |
