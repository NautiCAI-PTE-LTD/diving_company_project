#!/usr/bin/env bash
# First-time setup on Ubuntu 22.04 GCE VM (NVIDIA L4).
# Run: chmod +x deploy/gcp-l4/bootstrap-gce.sh && ./deploy/gcp-l4/bootstrap-gce.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "══════════════════════════════════════════════════════════════"
echo " NautiCAI · GCP GCE bootstrap (L4)"
echo " Repo: $ROOT"
echo "══════════════════════════════════════════════════════════════"

sudo apt-get update
sudo apt-get install -y \
    python3 python3-venv python3-pip \
    git curl ca-certificates \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1

if ! command -v gcloud &>/dev/null; then
  echo "[!] Install Google Cloud SDK on this VM for gsutil/gcloud storage, or"
  echo "    copy Models/ via scp from your laptop."
fi

if ! command -v nvidia-smi &>/dev/null; then
  echo "[!] nvidia-smi not found. Install NVIDIA driver 535+ and reboot before setup_gpu_models.sh"
fi

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel setuptools

mkdir -p /opt/nauticai/Models
if [[ ! -d "$ROOT/Models" ]] || [[ -z "$(ls -A "$ROOT/Models" 2>/dev/null)" ]]; then
  ln -sfn /opt/nauticai/Models "$ROOT/Models" 2>/dev/null || true
fi

mkdir -p backend/storage/uploads backend/storage/reports

if [[ ! -f backend/.env ]]; then
  cp deploy/gcp-l4/env.production.example backend/.env
  echo "[!] Edit backend/.env — set DATABASE_URL and JWT_SECRET"
fi

cat <<EOF

────────────────────────────────────────────────────────────────
 Next steps:

 1. export GCS_BUCKET=your-bucket-name
    ./deploy/gcp-l4/sync-from-gcs.sh

 2. source .venv/bin/activate && ./deploy/gcp-l4/setup_gpu_models.sh

 3. nano backend/.env

 4. uvicorn backend.main:app --host 0.0.0.0 --port 8000
    # or: sudo cp deploy/gcp-l4/nauticai-api.service /etc/systemd/system/ && sudo systemctl enable --now nauticai-api

 See deploy/gcp-l4/README.md for full procedure.
────────────────────────────────────────────────────────────────
EOF
